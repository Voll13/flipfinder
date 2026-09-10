from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.admin import AdminService, create_app
from app.config import Settings
from app.models import AIAnalysis, DeviceInfo, FlipEvaluation, Listing
from app.storage.database import Database


def service(tmp_path, cycle=None):
    async def default_cycle(args, settings):
        return None
    return AdminService(Settings(_env_file=None, openai_api_key="secret", telegram_bot_token="token", telegram_chat_id="123"), str(tmp_path / "admin.db"), cycle or default_cycle)


def test_admin_dashboard_status_settings_and_no_secrets(tmp_path):
    app = create_app(service(tmp_path))
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        status = client.get("/api/status").json()
        assert status["status"] == "STOPPED"
        settings = client.get("/api/settings").json()
        assert "openai_api_key" not in settings and "telegram_bot_token" not in settings
        updated = {**settings, "ai_limit": 3, "cities": ["Warsaw"], "models": ["iPhone 15"]}
        assert client.put("/api/settings", json=updated).json()["ai_limit"] == 3
        assert client.get("/api/settings").json()["cities"] == ["Warsaw"]


def test_telegram_report_language_is_defaulted_persisted_and_validated(tmp_path):
    app = create_app(service(tmp_path))
    with TestClient(app) as client:
        settings = client.get("/api/settings").json()
        assert settings["telegram_report_language"] == "ru"

        for language in ("ru", "pl"):
            response = client.put("/api/settings", json={**settings, "telegram_report_language": language})
            assert response.status_code == 200
            assert response.json()["telegram_report_language"] == language
            assert client.get("/api/settings").json()["telegram_report_language"] == language
            settings = response.json()

        invalid = client.put("/api/settings", json={**settings, "telegram_report_language": "en"})
        assert invalid.status_code == 422


def test_monitor_start_duplicate_stop_and_restart_are_lifecycle_safe(tmp_path):
    calls = []
    async def cycle(args, settings):
        calls.append(settings.ai_request_delay_seconds)
        await asyncio.sleep(10)
    app = create_app(service(tmp_path, cycle))
    with TestClient(app) as client:
        assert client.post("/api/monitor/start").json()["started"] is True
        assert client.post("/api/monitor/start").json()["started"] is False
        assert client.post("/api/monitor/stop").json()["stopped"] is True
        assert client.get("/api/status").json()["status"] == "STOPPED"
        assert client.post("/api/monitor/restart").json()["status"] in {"STARTING", "RUNNING"}
        client.post("/api/monitor/stop")


def test_admin_listing_dashboard_and_runs_use_existing_database(tmp_path):
    db_path = str(tmp_path / "admin.db")
    async def seed():
        async with Database(db_path) as db:
            item = Listing(source="olx", external_id="1", url="https://olx/1", title="iPhone 15 Pro", price=2000, location="Warsaw")
            identifier, _ = await db.upsert_listing(item)
            analysis = AIAnalysis(device_info=DeviceInfo(model="iPhone 15 Pro", storage_gb=128, condition="excellent"), estimated_resale_price=2600, resale_confidence=.8, fraud_risk=.1, summary="safe")
            evaluation = FlipEvaluation(scoring_version=2, flip_score=75, estimated_profit=600, margin_pct=30, resale_price_used=2600, resale_source="dynamic_market", resale_confidence_used=.7, market_sample_size=5, is_flip_candidate=True)
            await db.update_listing_analysis(identifier, analysis.device_info, analysis, evaluation)
            await db.record_monitoring_run("2026-01-01T00:00:00+00:00", "2026-01-01T00:01:00+00:00", 60, None, "success")
    asyncio.run(seed())
    app = create_app(AdminService(Settings(_env_file=None), db_path))
    with TestClient(app) as client:
        rows = client.get("/api/opportunities").json()
        assert rows[0]["external_id"] == "1" and "description" not in rows[0]
        assert client.get(f"/api/opportunities/{rows[0]['id']}").json()["evaluation"]["flip_score"] == 75
        assert client.get("/api/dashboard").json()["opportunities"] == 1
        assert client.get("/api/runs").json()[0]["status"] == "success"
