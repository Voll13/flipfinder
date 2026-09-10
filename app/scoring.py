"""Deterministic flip evaluation."""
from __future__ import annotations
from dataclasses import dataclass
from app.config import Settings
from app.models import AIAnalysis, FlipEvaluation, Listing, MarketPrice
from app.services.resale_estimator import ResaleEstimate

SCORING_VERSION = 2


@dataclass(frozen=True)
class ScoreBreakdown:
    """Inspectable components used by :meth:`FlipScorer.evaluate`."""

    profitability_component: float
    market_discount_component: float
    suspicious_low_price_penalty: float
    confidence_component: float
    condition_component: float
    package_component: float
    battery_component: float
    positive_base_component: float
    positive_signal_component: float
    positive_component: float
    risk_penalty: float
    red_flag_penalty: float
    hard_stop_reason: str | None
    score_before_clamp: float
    final_score: float
    estimated_profit: int
    margin_pct: float
    fees_estimate: int
    resale_price: int
    resale_confidence: float
    is_flip_candidate: bool

class FlipScorer:
    def __init__(self,settings:Settings)->None:self.settings=settings
    def _hard_stop(self,a:AIAnalysis)->str|None:
        d=a.device_info
        for field,label in ((d.icloud_locked,"iCloud lock"),(d.operator_locked,"operator lock"),(d.screen_damaged,"screen damaged"),(d.damaged,"device damaged")):
            if field:return label
        if (d.condition or "").casefold()=="damaged":return "damaged condition"
        flags=" ".join(a.red_flags).casefold()
        return "red flag indicates lock/parts" if any(x in flags for x in ("icloud lock","mdm lock","imei blacklist","for parts","sold for parts")) else None

    def explain(self, listing: Listing, analysis: AIAnalysis, market: MarketPrice | None = None, resale_estimate: ResaleEstimate | None = None) -> ScoreBreakdown:
        """Return the exact score arithmetic without changing the evaluation decision."""
        resale_price = resale_estimate.price if resale_estimate else analysis.estimated_resale_price
        resale_confidence = resale_estimate.confidence if resale_estimate else analysis.resale_confidence
        fees = round(resale_price * self.settings.marketplace_fee_pct / 100)
        profit = resale_price - listing.price - fees
        margin = profit / listing.price * 100 if listing.price else 0.0
        profitability = max(0, min(40, margin))

        market_discount = 0.0
        suspicious_low_price_penalty = 0.0
        if market and market.currency == listing.currency and market.avg_price > 0:
            discount = max(0, (market.avg_price - listing.price) / market.avg_price * 100)
            market_discount = min(20, discount / 2)
            if listing.price < market.min_price * 0.5:
                # The production scorer subtracts this from the market component
                # with a floor at zero; record the effective rather than nominal
                # penalty so the breakdown always sums exactly.
                suspicious_low_price_penalty = min(5.0, market_discount)

        device = analysis.device_info
        condition = {"new": 10, "excellent": 9, "good": 7, "fair": 4, "damaged": 0}.get((device.condition or "").casefold(), 4)
        package = sum(points for value, points in ((device.has_box, 2), (device.has_receipt, 3), (device.has_warranty, 3)) if value)
        battery = 0
        if device.battery_health is not None:
            if device.battery_health >= 90:
                battery = 2
            elif device.battery_health >= 85:
                battery = 1
            elif device.battery_health < 80:
                battery = -3
        positive_base = min(10, max(0, package + battery))
        positive_signals = min(2, len(set(analysis.positive_signals)))
        positive = positive_base + positive_signals
        risk = min(40, analysis.fraud_risk * 30)
        before_clamp = profitability + market_discount - suspicious_low_price_penalty + resale_confidence * 10 + condition + positive - risk
        final_score = round(max(0, min(100, before_clamp)), 1)
        hard_stop = self._hard_stop(analysis)
        candidate = bool(listing.price > 0 and profit > 0 and margin >= self.settings.min_margin_pct and final_score >= self.settings.min_flip_score and analysis.fraud_risk <= self.settings.max_fraud_risk and not hard_stop)
        return ScoreBreakdown(
            profitability, market_discount, suspicious_low_price_penalty, resale_confidence * 10,
            condition, package, battery, positive_base, positive_signals, positive,
            risk, 0.0, hard_stop, before_clamp, final_score, profit, round(margin, 1),
            fees, resale_price, resale_confidence, candidate,
        )

    def evaluate(self,listing:Listing,analysis:AIAnalysis,market:MarketPrice|None=None,resale_estimate:ResaleEstimate|None=None)->FlipEvaluation:
        breakdown = self.explain(listing, analysis, market, resale_estimate)
        resale_price = breakdown.resale_price
        resale_source = resale_estimate.source if resale_estimate else "llm_fallback"
        reasons=[f"Expected profit: {breakdown.estimated_profit} PLN",f"Expected margin: {breakdown.margin_pct:.1f}%"]
        if market and market.currency==listing.currency and market.avg_price>0:
            discount=max(0,(market.avg_price-listing.price)/market.avg_price*100)
            if discount:reasons.append(f"Asking price is {discount:.0f}% below market average")
            if breakdown.suspicious_low_price_penalty: reasons.append("Suspiciously low price")
        d=analysis.device_info
        for value,points,label in ((d.has_box,2,"Original box included"),(d.has_receipt,3,"Receipt available"),(d.has_warranty,3,"Warranty active")):
            if value: reasons.append(label)
        if d.battery_health is not None:
            if d.battery_health>=90: reasons.append(f"Battery health: {d.battery_health}%")
            elif d.battery_health<80: reasons.append(f"Low battery health: {d.battery_health}%")
        label="low" if analysis.fraud_risk<.2 else "moderate" if analysis.fraud_risk<.5 else "high" if analysis.fraud_risk<.8 else "very high"; reasons.append(f"Fraud risk: {label}")
        for flag in list(dict.fromkeys(analysis.red_flags))[:3]:reasons.append(f"Red flag: {flag}")
        stop=breakdown.hard_stop_reason
        if stop:reasons.append(f"Hard stop: {stop}")
        if analysis.recommended_buy_price is not None and listing.price<=analysis.recommended_buy_price:reasons.append("Asking price is within AI recommended buy range")
        return FlipEvaluation(scoring_version=SCORING_VERSION,flip_score=breakdown.final_score,estimated_profit=breakdown.estimated_profit,margin_pct=breakdown.margin_pct,fees_estimate=breakdown.fees_estimate,is_flip_candidate=breakdown.is_flip_candidate,reasons=reasons[:10],resale_price_used=resale_price,resale_source=resale_source,resale_confidence_used=breakdown.resale_confidence,market_sample_size=resale_estimate.market_sample_size if resale_estimate else (market.sample_size if market else None))
