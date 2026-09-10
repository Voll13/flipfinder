from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.admin import AdminService, create_app
from app.config import Settings
from app.models import AIAnalysis, DeviceInfo, FlipEvaluation, Listing
from app.storage.database import Database


def _client(tmp_path):
    db_path = str(tmp_path / "review.db")

    async def seed():
        async with Database(db_path) as db:
            for external_id, price, score, profit in [("1", 1000, 75, 900), ("2", 1200, 70, 500)]:
                listing = Listing(source="olx", external_id=external_id, url=f"https://olx/{external_id}", title=f"iPhone 15 {external_id}", price=price, location="Warsaw")
                listing_id, _ = await db.upsert_listing(listing)
                analysis = AIAnalysis(device_info=DeviceInfo(model="iPhone 15", storage_gb=128, condition="good"), estimated_resale_price=1900, resale_confidence=.8, fraud_risk=.1, summary="review test")
                evaluation = FlipEvaluation(scoring_version=2, flip_score=score, estimated_profit=profit, margin_pct=profit / price * 100, resale_price_used=1900, resale_source="dynamic_market", resale_confidence_used=.7, market_sample_size=5, is_flip_candidate=True)
                await db.update_listing_analysis(listing_id, analysis.device_info, analysis, evaluation)
                if external_id == "1": await db.mark_sent(listing_id)
    asyncio.run(seed())
    service = AdminService(Settings(_env_file=None), db_path)
    return TestClient(create_app(service))


def test_review_status_note_and_favorite_do_not_change_candidate_or_sent(tmp_path):
    with _client(tmp_path) as client:
        listing = next(item for item in client.get("/api/opportunities").json() if item["is_sent"])
        updated = client.patch(f"/api/opportunities/{listing['id']}/review", json={"review_status": "interesting", "review_note": "Ask for IMEI", "favorite": True})
        assert updated.status_code == 200
        body = updated.json()
        assert body["review_status"] == "interesting" and body["review_note"] == "Ask for IMEI" and body["favorite"] is True
        assert body["evaluation"]["is_flip_candidate"] is True and body["is_sent"] is True


def test_review_validation_filters_sorting_and_pagination(tmp_path):
    with _client(tmp_path) as client:
        first = client.get("/api/opportunities?sort=profit&page_size=1").json()
        assert len(first) == 1 and first[0]["evaluation"]["estimated_profit"] == 900
        assert client.get("/api/opportunities?review_status=invalid").status_code == 422
        listing_id = first[0]["id"]
        assert client.patch(f"/api/opportunities/{listing_id}/review", json={"review_status": "reviewing"}).status_code == 200
        filtered = client.get("/api/opportunities?review_status=reviewing").json()
        assert [row["id"] for row in filtered] == [listing_id]
        assert client.get("/api/opportunities?favorite=true").json() == []
