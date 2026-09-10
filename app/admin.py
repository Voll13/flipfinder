"""Local FastAPI control center for the production monitor."""
from __future__ import annotations

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.main import _run_once
from app.services.market_benchmark import MarketBenchmarkBuilder
from app.services.monitor_controller import MonitorController
from app.storage.database import Database

ROOT = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(ROOT / "templates"))
logger = logging.getLogger(__name__)
FAMILIES = ["iPhone 13", "iPhone 14", "iPhone 15", "iPhone 16"]
REVIEW_STATUSES = {"new", "reviewing", "interesting", "rejected", "purchased", "archived"}


def default_admin_settings(settings: Settings) -> dict[str, Any]:
    return {
        "monitor_interval_minutes": settings.monitor_interval_minutes,
        "market_pages": 5,
        "ai_limit": 5,
        "ai_request_delay_seconds": settings.ai_request_delay_seconds,
        "market_lookback_hours": settings.market_lookback_hours,
        "models": list(settings.search_queries or FAMILIES),
        "cities": [], "voivodeships": [],
        "min_flip_score": settings.min_flip_score,
        "min_margin_pct": settings.min_margin_pct,
        "max_fraud_risk": settings.max_fraud_risk,
        "telegram_report_language": "ru",
    }


def validate_admin_settings(values: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    result = {**defaults, **{key: value for key, value in values.items() if key in defaults}}
    for key in ("models", "cities", "voivodeships"):
        if not isinstance(result[key], list) or not all(isinstance(value, str) and value.strip() for value in result[key]):
            raise ValueError(f"{key} must be a list of non-empty strings")
        result[key] = [value.strip() for value in result[key]]
    result["monitor_interval_minutes"] = int(result["monitor_interval_minutes"])
    result["market_pages"] = int(result["market_pages"])
    result["ai_limit"] = int(result["ai_limit"])
    result["ai_request_delay_seconds"] = float(result["ai_request_delay_seconds"])
    result["market_lookback_hours"] = int(result["market_lookback_hours"])
    result["min_flip_score"] = float(result["min_flip_score"])
    result["min_margin_pct"] = float(result["min_margin_pct"])
    result["max_fraud_risk"] = float(result["max_fraud_risk"])
    if result["telegram_report_language"] not in {"ru", "pl"}: raise ValueError("telegram_report_language must be ru or pl")
    if not 5 <= result["monitor_interval_minutes"] <= 1440: raise ValueError("monitor_interval_minutes must be 5–1440")
    if not 1 <= result["market_pages"] <= 5: raise ValueError("market_pages must be 1–5")
    if result["ai_limit"] < 1: raise ValueError("ai_limit must be >= 1")
    if result["ai_request_delay_seconds"] < 0: raise ValueError("ai_request_delay_seconds must be >= 0")
    if result["market_lookback_hours"] < 1: raise ValueError("market_lookback_hours must be >= 1")
    if not 0 <= result["min_flip_score"] <= 100 or result["min_margin_pct"] < 0 or not 0 <= result["max_fraud_risk"] <= 1:
        raise ValueError("threshold values are outside their valid range")
    return result


class AdminService:
    def __init__(self, base_settings: Settings, database_path: str | None = None, cycle_runner=_run_once) -> None:
        self.base_settings = base_settings
        self.database_path = database_path or base_settings.database_path
        self._cycle_runner = cycle_runner
        self.defaults = default_admin_settings(base_settings)
        self.controller = MonitorController(self.run_cycle, self.interval_seconds)

    async def settings(self) -> dict[str, Any]:
        async with Database(self.database_path) as db:
            saved = await db.get_app_settings()
        return validate_admin_settings(saved, self.defaults)

    async def save_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        configured = validate_admin_settings(values, self.defaults)
        async with Database(self.database_path) as db:
            await db.set_app_settings(configured)
        self.defaults = {**self.defaults, **configured}
        return configured

    def interval_seconds(self) -> float:
        # Controller invokes this between cycles. Persisted changes therefore do
        # not interrupt a running browser/AI cycle.
        return float(self.defaults["monitor_interval_minutes"] * 60)

    async def run_cycle(self) -> None:
        configured = await self.settings()
        self.defaults = {**self.defaults, **configured}
        runtime = Settings(
            monitor_interval_minutes=configured["monitor_interval_minutes"],
            ai_request_delay_seconds=configured["ai_request_delay_seconds"],
            market_lookback_hours=configured["market_lookback_hours"],
            min_flip_score=configured["min_flip_score"], min_margin_pct=configured["min_margin_pct"],
            max_fraud_risk=configured["max_fraud_risk"],
        )
        args = SimpleNamespace(
            pages=None, limit=configured["ai_limit"], market_pages=configured["market_pages"], market_only=False,
            html_file=None, browser=True, database=self.database_path, query=configured["models"], external_id=None,
            model=None, city=configured["cities"] or None, voivodeship=configured["voivodeships"] or None, dry_run=False,
        )
        started = datetime.now(timezone.utc)
        stats = None
        status, message = "success", None
        try:
            stats = await self._cycle_runner(args, runtime)
            if stats and stats.errors:
                status = "partial"
        except asyncio.CancelledError:
            status = "partial"; message = "Cycle cancelled during graceful stop"
            raise
        except Exception as exc:
            status, message = "error", str(exc)[:500]
            raise
        finally:
            finished = datetime.now(timezone.utc)
            async with Database(self.database_path) as db:
                run_id = await db.record_monitoring_run(started.isoformat(), finished.isoformat(), (finished - started).total_seconds(), stats, status, message)
                if status == "success":
                    universe = await db.get_market_universe(configured["market_lookback_hours"])
                    await db.save_market_benchmark_snapshot(run_id, finished.isoformat(), MarketBenchmarkBuilder().build(universe))


def create_app(service: AdminService | None = None) -> FastAPI:
    service = service or AdminService(Settings())
    app = FastAPI(title="Flip Finder Control Center", docs_url=None, redoc_url=None)
    app.state.service = service
    app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")

    async def db() -> Database:
        # Kept as an explicit helper so every endpoint reads the production DB.
        database = Database(service.database_path); await database.__aenter__(); return database

    @app.get("/", response_class=HTMLResponse)
    @app.get("/{page}", response_class=HTMLResponse)
    async def page(request: Request, page: str = "dashboard"):
        if page not in {"dashboard", "opportunities", "market", "runs", "logs", "settings"}: raise HTTPException(404)
        return TEMPLATES.TemplateResponse(request, "dashboard.html", {"page": page, "families": FAMILIES})

    @app.get("/api/status")
    async def status(): return service.controller.snapshot()

    @app.post("/api/monitor/start")
    async def start_monitor(): return {"started": await service.controller.start(), **service.controller.snapshot()}

    @app.post("/api/monitor/stop")
    async def stop_monitor(): return {"stopped": await service.controller.stop(), **service.controller.snapshot()}

    @app.post("/api/monitor/restart")
    async def restart_monitor(): await service.controller.restart(); return service.controller.snapshot()

    @app.get("/api/settings")
    async def get_settings(): return await service.settings()

    @app.put("/api/settings")
    async def put_settings(payload: dict[str, Any]):
        try: return await service.save_settings(payload)
        except (ValueError, TypeError) as exc: raise HTTPException(422, str(exc)) from exc

    @app.get("/api/dashboard")
    async def dashboard():
        async with Database(service.database_path) as database:
            counts = await database.admin_dashboard_counts(); runs = await database.list_monitoring_runs(1)
            if runs:
                run = runs[0]; checked = run["market_available"] + run["market_unavailable"]
                counts.update({"current_listings": run["current_listings"], "query_candidates": run["query_candidates"], "market_eligible": run["market_available"], "errors": run["errors"], "coverage_pct": round(run["market_available"] / checked * 100, 1) if checked else 0, "last_run": run})
            return counts

    @app.get("/api/opportunities")
    async def opportunities(kind: str = "opportunities", model: str | None = None, storage: int | None = None,
        city: str | None = None, review_status: str | None = None, risk: float | None = Query(default=None, ge=0, le=1),
        min_score: float | None = Query(default=None, ge=0, le=100), min_margin: float | None = Query(default=None, ge=0),
        sent: bool | None = None, active: bool | None = True, favorite: bool | None = None,
        sort: str = "newest", page: int = Query(default=1, ge=1), page_size: int = Query(default=25, ge=1, le=100), limit: int | None = None):
        if kind not in {"opportunities", "recent", "near_misses", "sent"}: raise HTTPException(422, "invalid listing kind")
        if review_status is not None and review_status not in REVIEW_STATUSES: raise HTTPException(422, "invalid review status")
        if sort not in {"newest", "profit", "margin", "score", "risk", "asking"}: raise HTTPException(422, "invalid sort")
        if limit is not None: page_size = min(max(limit, 1), 100)
        if kind == "sent": sent = True; kind = "opportunities"
        async with Database(service.database_path) as database:
            return await database.admin_query_listings(kind, model=model, storage=storage, city=city, review_status=review_status,
                risk=risk, min_score=min_score, min_margin=min_margin, sent=sent, active=active, favorite=favorite,
                sort=sort, page=page, page_size=page_size)

    @app.get("/api/opportunities/compare")
    async def compare_opportunities(ids: str):
        try: selected = [int(value) for value in ids.split(",") if value]
        except ValueError as exc: raise HTTPException(422, "invalid comparison ids") from exc
        if not 2 <= len(selected) <= 4 or len(set(selected)) != len(selected): raise HTTPException(422, "comparison requires 2–4 unique listings")
        async with Database(service.database_path) as database:
            rows = await database.admin_query_listings("recent", active=None, page_size=100)
        result = [row for row in rows if row["id"] in selected]
        if len(result) != len(selected): raise HTTPException(404, "listing not found")
        return result

    @app.get("/api/opportunities/{listing_id}")
    async def opportunity_detail(listing_id: int):
        async with Database(service.database_path) as database:
            rows = await database.admin_query_listings("recent", active=None, page_size=100)
        row = next((item for item in rows if item["id"] == listing_id), None)
        if row is None: raise HTTPException(404)
        async with Database(service.database_path) as database:
            row["price_history"] = await database.get_price_history(listing_id)
        return row

    @app.patch("/api/opportunities/{listing_id}/review")
    async def review_opportunity(listing_id: int, payload: dict[str, Any]):
        allowed = {"review_status", "review_note", "favorite"}
        if not payload or set(payload) - allowed: raise HTTPException(422, "invalid review payload")
        review_status = payload.get("review_status")
        if review_status is not None and review_status not in REVIEW_STATUSES: raise HTTPException(422, "invalid review status")
        note = payload.get("review_note")
        if note is not None and (not isinstance(note, str) or len(note) > 4000): raise HTTPException(422, "invalid review note")
        favorite = payload.get("favorite")
        if favorite is not None and not isinstance(favorite, bool): raise HTTPException(422, "invalid favorite")
        async with Database(service.database_path) as database:
            raw = await database.update_listing_review(listing_id, review_status, note, favorite)
            if raw is None: raise HTTPException(404)
            rows = await database.admin_query_listings("recent", active=None, page_size=100)
        result = next((item for item in rows if item["id"] == listing_id), None)
        if result is None: raise HTTPException(404)
        return result

    @app.get("/api/market")
    async def market():
        configured = await service.settings()
        async with Database(service.database_path) as database:
            universe = await database.get_market_universe(configured["market_lookback_hours"])
        return [item.model_dump(mode="json") for item in MarketBenchmarkBuilder().build(universe)]

    @app.get("/api/market/history")
    async def market_history(model: str, storage: int, condition: str, hours: int = Query(default=72, ge=1, le=720)):
        async with Database(service.database_path) as database:
            return await database.get_market_benchmark_history(model, storage, condition, hours)
    @app.get("/api/market/trends")
    async def market_trends():
        async with Database(service.database_path) as database: return await database.get_market_trends()

    @app.get("/api/runs")
    async def runs(limit: int = 50):
        async with Database(service.database_path) as database: return await database.list_monitoring_runs(min(max(limit, 1), 200))

    @app.get("/api/logs")
    async def logs():
        path = Path("logs/flip_finder.log")
        if not path.exists(): return {"lines": []}
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]
        return {"lines": [line for line in lines if "API_KEY" not in line and "BOT_TOKEN" not in line]}

    return app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the local Flip Finder admin panel")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    Path("logs").mkdir(exist_ok=True)
    root = logging.getLogger()
    root.addHandler(RotatingFileHandler("logs/flip_finder.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"))
    import uvicorn
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="info")


if __name__ == "__main__": main()
