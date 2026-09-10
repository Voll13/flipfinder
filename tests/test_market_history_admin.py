from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.models import MarketPrice
from app.storage.database import Database


def test_market_snapshot_stores_only_valid_groups_once_and_history_filters(tmp_path):
    path = str(tmp_path / "history.db")
    async def run():
        async with Database(path) as db:
            run_id = await db.record_monitoring_run("2026-01-01T00:00:00+00:00", datetime.now(timezone.utc).isoformat(), 1, None, "success")
            valid = MarketPrice(model="iPhone 15 Pro", storage_gb=256, condition="good", min_price=2000, median_price=2300, avg_price=2350, max_price=2500, sample_size=3)
            invalid = MarketPrice(model="iPhone 15", storage_gb=128, condition="good", min_price=1000, median_price=1200, avg_price=1200, max_price=1400, sample_size=2)
            assert await db.save_market_benchmark_snapshot(run_id, datetime.now(timezone.utc).isoformat(), [valid, invalid]) == 1
            assert await db.save_market_benchmark_snapshot(run_id, datetime.now(timezone.utc).isoformat(), [valid]) == 0
            history = await db.get_market_benchmark_history("iPhone 15 Pro", 256, "good", 72)
            assert len(history) == 1 and history[0]["median_price"] == 2300
            assert await db.get_market_benchmark_history("iPhone 15", 128, "good", 72) == []
    asyncio.run(run())
