from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.models import (
    AIAnalysis,
    DeviceInfo,
    FlipEvaluation,
    Listing,
    MarketPrice,
)


# ── Listing ──────────────────────────────────────────


class TestListing:
    def _valid_listing(self, **overrides: object) -> Listing:
        data = {
            "source": "olx",
            "external_id": "abc123",
            "url": "https://olx.pl/d/oferta/abc123",
            "title": "iPhone 14 Pro 128GB",
            "price": 3500,
        }
        data.update(overrides)
        return Listing(**data)

    def test_valid_listing(self) -> None:
        listing = self._valid_listing()
        assert listing.source == "olx"
        assert listing.price == 3500
        assert listing.currency == "PLN"
        assert listing.photo_urls == []
        assert listing.attributes == {}
        assert listing.is_active is True

    def test_negative_price(self) -> None:
        with pytest.raises(ValidationError, match="price"):
            self._valid_listing(price=-100)

    def test_zero_price_allowed(self) -> None:
        listing = self._valid_listing(price=0)
        assert listing.price == 0

    def test_empty_title(self) -> None:
        with pytest.raises(ValidationError, match="title"):
            self._valid_listing(title="")

    def test_whitespace_only_title(self) -> None:
        with pytest.raises(ValidationError, match="title"):
            self._valid_listing(title="   ")

    def test_empty_external_id(self) -> None:
        with pytest.raises(ValidationError, match="external_id"):
            self._valid_listing(external_id="")

    def test_empty_url(self) -> None:
        with pytest.raises(ValidationError, match="url"):
            self._valid_listing(url="")

    def test_mutable_defaults_independent(self) -> None:
        listing_a = self._valid_listing()
        listing_b = self._valid_listing()
        listing_a.photo_urls.append("https://img1.jpg")
        assert listing_b.photo_urls == []

    def test_all_sources(self) -> None:
        olx = self._valid_listing(source="olx")
        allegro = self._valid_listing(source="allegro")
        assert olx.source == "olx"
        assert allegro.source == "allegro"

    def test_invalid_source(self) -> None:
        with pytest.raises(ValidationError):
            self._valid_listing(source="ebay")


# ── DeviceInfo ───────────────────────────────────────


class TestDeviceInfo:
    def test_all_none_by_default(self) -> None:
        device = DeviceInfo()
        assert device.model is None
        assert device.storage_gb is None
        assert device.battery_health is None

    def test_valid_battery_health(self) -> None:
        device = DeviceInfo(battery_health=85)
        assert device.battery_health == 85

    def test_battery_health_boundaries(self) -> None:
        assert DeviceInfo(battery_health=0).battery_health == 0
        assert DeviceInfo(battery_health=100).battery_health == 100

    def test_battery_health_too_high(self) -> None:
        with pytest.raises(ValidationError, match="battery_health"):
            DeviceInfo(battery_health=101)

    def test_battery_health_negative(self) -> None:
        with pytest.raises(ValidationError, match="battery_health"):
            DeviceInfo(battery_health=-1)

    def test_valid_storage(self) -> None:
        device = DeviceInfo(storage_gb=256)
        assert device.storage_gb == 256

    def test_zero_storage(self) -> None:
        with pytest.raises(ValidationError, match="storage_gb"):
            DeviceInfo(storage_gb=0)

    def test_negative_storage(self) -> None:
        with pytest.raises(ValidationError, match="storage_gb"):
            DeviceInfo(storage_gb=-1)

    def test_full_device(self) -> None:
        device = DeviceInfo(
            model="iPhone 15 Pro",
            storage_gb=256,
            battery_health=92,
            condition="good",
            color="Natural Titanium",
            has_box=True,
            has_receipt=False,
            has_warranty=True,
            damaged=False,
            screen_damaged=False,
            icloud_locked=False,
            operator_locked=False,
            sim_type="esim",
        )
        assert device.model == "iPhone 15 Pro"
        assert device.damaged is False


# ── MarketPrice ──────────────────────────────────────


class TestMarketPrice:
    def _valid_price(self, **overrides: object) -> MarketPrice:
        data = {
            "model": "iPhone 14 Pro",
            "storage_gb": 128,
            "condition": "good",
            "avg_price": 3500,
            "min_price": 2800,
            "max_price": 4200,
        }
        data.update(overrides)
        return MarketPrice(**data)

    def test_valid_price(self) -> None:
        mp = self._valid_price()
        assert mp.avg_price == 3500
        assert mp.sample_size == 0

    def test_min_greater_than_avg(self) -> None:
        with pytest.raises(ValidationError, match="avg_price"):
            self._valid_price(min_price=4000, avg_price=3500)

    def test_avg_greater_than_max(self) -> None:
        with pytest.raises(ValidationError, match="max_price"):
            self._valid_price(avg_price=5000, max_price=4200)

    def test_negative_price(self) -> None:
        with pytest.raises(ValidationError, match="price"):
            self._valid_price(avg_price=-100)

    def test_negative_sample_size(self) -> None:
        with pytest.raises(ValidationError, match="sample_size"):
            self._valid_price(sample_size=-1)

    def test_equal_prices(self) -> None:
        mp = self._valid_price(min_price=3000, avg_price=3000, max_price=3000)
        assert mp.min_price == mp.avg_price == mp.max_price


# ── AIAnalysis ───────────────────────────────────────


class TestAIAnalysis:
    def _valid_analysis(self, **overrides: object) -> AIAnalysis:
        data = {
            "device_info": DeviceInfo(model="iPhone 14", storage_gb=128, condition="good"),
            "estimated_resale_price": 3200,
            "resale_confidence": 0.8,
            "fraud_risk": 0.1,
            "summary": "Good deal, minor scratches.",
        }
        data.update(overrides)
        return AIAnalysis(**data)

    def test_valid_analysis(self) -> None:
        analysis = self._valid_analysis()
        assert analysis.device_info.model == "iPhone 14"
        assert analysis.estimated_resale_price == 3200
        assert analysis.red_flags == []
        assert analysis.positive_signals == []

    def test_fraud_risk_above_one(self) -> None:
        with pytest.raises(ValidationError, match="fraud_risk"):
            self._valid_analysis(fraud_risk=1.5)

    def test_fraud_risk_below_zero(self) -> None:
        with pytest.raises(ValidationError, match="fraud_risk"):
            self._valid_analysis(fraud_risk=-0.1)

    def test_resale_confidence_below_zero(self) -> None:
        with pytest.raises(ValidationError, match="resale_confidence"):
            self._valid_analysis(resale_confidence=-0.1)

    def test_resale_confidence_above_one(self) -> None:
        with pytest.raises(ValidationError, match="resale_confidence"):
            self._valid_analysis(resale_confidence=1.1)

    def test_negative_resale_price(self) -> None:
        with pytest.raises(ValidationError, match="estimated_resale_price"):
            self._valid_analysis(estimated_resale_price=-100)

    def test_negative_buy_price(self) -> None:
        with pytest.raises(ValidationError, match="recommended_buy_price"):
            self._valid_analysis(recommended_buy_price=-50)

    def test_buy_price_none_allowed(self) -> None:
        analysis = self._valid_analysis(recommended_buy_price=None)
        assert analysis.recommended_buy_price is None

    def test_mutable_defaults_independent(self) -> None:
        a = self._valid_analysis()
        b = self._valid_analysis()
        a.red_flags.append("suspicious")
        assert b.red_flags == []


# ── FlipEvaluation ───────────────────────────────────


class TestFlipEvaluation:
    def _valid_eval(self, **overrides: object) -> FlipEvaluation:
        data = {
            "flip_score": 75.0,
            "estimated_profit": 800,
            "margin_pct": 22.5,
            "is_flip_candidate": True,
            "reasons": ["Good margin", "Low fraud risk"],
        }
        data.update(overrides)
        return FlipEvaluation(**data)

    def test_valid_evaluation(self) -> None:
        ev = self._valid_eval()
        assert ev.flip_score == 75.0
        assert ev.is_flip_candidate is True
        assert ev.fees_estimate == 0

    def test_negative_profit_allowed(self) -> None:
        ev = self._valid_eval(estimated_profit=-200)
        assert ev.estimated_profit == -200

    def test_negative_margin_allowed(self) -> None:
        ev = self._valid_eval(margin_pct=-10.5)
        assert ev.margin_pct == -10.5

    def test_flip_score_above_100(self) -> None:
        with pytest.raises(ValidationError, match="flip_score"):
            self._valid_eval(flip_score=101.0)

    def test_flip_score_below_zero(self) -> None:
        with pytest.raises(ValidationError, match="flip_score"):
            self._valid_eval(flip_score=-1.0)

    def test_negative_fees(self) -> None:
        with pytest.raises(ValidationError, match="fees_estimate"):
            self._valid_eval(fees_estimate=-10)

    def test_boundary_scores(self) -> None:
        assert self._valid_eval(flip_score=0.0).flip_score == 0.0
        assert self._valid_eval(flip_score=100.0).flip_score == 100.0

    def test_mutable_defaults_independent(self) -> None:
        a = self._valid_eval()
        b = self._valid_eval()
        a.reasons.append("extra")
        assert b.reasons == ["Good margin", "Low fraud risk"]
