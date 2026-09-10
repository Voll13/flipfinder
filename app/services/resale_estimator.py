"""Deterministic resale estimate derived from a comparable market benchmark."""
from __future__ import annotations

from dataclasses import dataclass

from app.models import AIAnalysis, Listing, MarketPrice


CONDITION_ADJUSTMENTS = {
    "new": 0.05,
    "excellent": 0.03,
    "good": 0.0,
    "fair": -0.10,
    "damaged": -0.25,
}
BATTERY_ADJUSTMENTS = (
    (95, 0.02),
    (90, 0.0),
    (85, -0.03),
    (80, -0.07),
    (0, -0.12),
)
PACKAGE_ADJUSTMENTS = (
    ("has_box", 0.01, "box +1%"),
    ("has_receipt", 0.01, "receipt +1%"),
    ("has_warranty", 0.02, "warranty +2%"),
)
CONFIDENCE_BY_SAMPLE = ((15, 0.90), (8, 0.80), (5, 0.70), (4, 0.60), (3, 0.55))
ORDINARY_MIN_ADJUSTMENT = -0.20
ORDINARY_MAX_ADJUSTMENT = 0.10
DAMAGE_OR_LOCK_ADJUSTMENT = -0.35
DAMAGE_OR_LOCK_MIN_ADJUSTMENT = -0.60


@dataclass(frozen=True)
class ResaleEstimate:
    price: int
    confidence: float
    source: str
    base_price: int
    adjustments: list[str]
    market_sample_size: int
    market_min: int
    market_median: int | None
    market_avg: int
    market_max: int


class ResaleEstimator:
    """Apply small, inspectable adjustments to the comparable-market anchor."""

    @staticmethod
    def _sample_confidence(sample_size: int) -> float:
        for threshold, confidence in CONFIDENCE_BY_SAMPLE:
            if sample_size >= threshold:
                return confidence
        return 0.0

    @staticmethod
    def _battery_adjustment(battery: int) -> float:
        for threshold, adjustment in BATTERY_ADJUSTMENTS:
            if battery >= threshold:
                return adjustment
        return 0.0

    def estimate(
        self,
        listing: Listing,
        analysis: AIAnalysis,
        market: MarketPrice | None,
        market_source: str,
    ) -> ResaleEstimate | None:
        del listing  # Purchase price is intentionally excluded from resale valuation.
        if market is None:
            return None

        device = analysis.device_info
        market_condition = (market.condition or "").casefold()
        condition = (device.condition or "").casefold()
        adjustments: list[str] = []
        total = 0.0
        unknown_condition = condition not in CONDITION_ADJUSTMENTS

        if market_condition == "refurbished":
            # This segment already prices the refurbisher's cosmetic condition.
            pass
        elif unknown_condition:
            total -= 0.03
            adjustments.append("unknown condition -3%")
        elif not (market_condition == "new" and condition == "new"):
            adjustment = CONDITION_ADJUSTMENTS[condition]
            total += adjustment
            if adjustment:
                adjustments.append(f"condition {condition} {adjustment:+.0%}")

        if device.battery_health is not None and market_condition != "new":
            adjustment = self._battery_adjustment(device.battery_health)
            total += adjustment
            if adjustment:
                adjustments.append(f"battery {device.battery_health}% {adjustment:+.0%}")

        for field, adjustment, label in PACKAGE_ADJUSTMENTS:
            if getattr(device, field):
                total += adjustment
                adjustments.append(label)

        damaged_or_locked = any((
            device.icloud_locked,
            device.operator_locked,
            device.screen_damaged,
            device.damaged,
            condition == "damaged",
        ))
        if damaged_or_locked:
            total += DAMAGE_OR_LOCK_ADJUSTMENT
            total = max(DAMAGE_OR_LOCK_MIN_ADJUSTMENT, total)
            adjustments.append("damage or lock risk -35%")
        else:
            total = min(ORDINARY_MAX_ADJUSTMENT, max(ORDINARY_MIN_ADJUSTMENT, total))

        base_price = market.median_price if market.median_price is not None else market.avg_price
        price = max(0, round(base_price * (1 + total)))
        if not damaged_or_locked and condition in {"new", "excellent", "good"}:
            price = min(price, market.max_price)

        confidence = self._sample_confidence(market.sample_size)
        if unknown_condition:
            confidence -= 0.10
        if device.battery_health is None:
            confidence -= 0.03
        confidence = round(max(0.0, min(1.0, confidence)), 2)

        return ResaleEstimate(
            price=price,
            confidence=confidence,
            source=market_source,
            base_price=base_price,
            adjustments=adjustments,
            market_sample_size=market.sample_size,
            market_min=market.min_price,
            market_median=market.median_price,
            market_avg=market.avg_price,
            market_max=market.max_price,
        )
