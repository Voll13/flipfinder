"""Deterministic dynamic benchmarks built from comparable OLX listings."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, median, quantiles

from app.models import Listing, MarketPrice
from app.services.device_attributes import canonicalize_iphone_model, canonicalize_storage
from app.services.market_data import MarketDataProvider

MIN_BENCHMARK_SAMPLE = 3


def market_key(listing: Listing) -> tuple[str, int, str, str] | None:
    """Return the exact comparable-market key derived from OLX attributes."""
    model = canonicalize_iphone_model(listing.attributes.get("phonemodel"))
    storage = canonicalize_storage(listing.attributes.get("builtinmemory_phones"))
    if storage is None:
        _, storage = MarketDataProvider("").extract_device_hint(listing.title)
    condition = {"new": "new", "used": "good", "refurbished": "refurbished"}.get(listing.attributes.get("state", "").casefold())
    return (model, storage, condition, listing.currency) if model and storage and condition else None


@dataclass(frozen=True)
class BenchmarkDiagnostics:
    model: str
    storage_gb: int
    condition: str
    currency: str
    raw_sample_size: int
    clean_sample_size: int
    min_price: int | None
    median_price: int | None
    mean_price: int | None
    max_price: int | None
    removed_outliers: int


class MarketBenchmarkBuilder:
    """Build exact model, storage and OLX-condition market benchmarks."""

    def __init__(self) -> None:
        self.diagnostics: list[BenchmarkDiagnostics] = []
        self._title_hints = MarketDataProvider("")

    def _key(self, listing: Listing) -> tuple[str, int, str, str] | None:
        return market_key(listing)

    def comparable_count_for_listing(self, listing: Listing, universe: list[Listing]) -> int:
        key = self._key(listing)
        if key is None:
            return 0
        return sum(
            self._key(item) == key
            and (item.source, item.external_id) != (listing.source, listing.external_id)
            for item in universe
        )

    @staticmethod
    def _clean_prices(prices: list[int]) -> list[int]:
        if len(prices) < 5:
            return prices
        q1, _, q3 = quantiles(prices, n=4, method="inclusive")
        spread = q3 - q1
        low, high = q1 - 1.5 * spread, q3 + 1.5 * spread
        return [price for price in prices if low <= price <= high]

    def _calculate(self, key: tuple[str, int, str, str], prices: list[int]) -> tuple[MarketPrice | None, BenchmarkDiagnostics]:
        clean = self._clean_prices(prices)
        model, storage, condition, currency = key
        diagnostic = BenchmarkDiagnostics(model, storage, condition, currency, len(prices), len(clean), min(clean) if clean else None, round(median(clean)) if clean else None, round(mean(clean)) if clean else None, max(clean) if clean else None, len(prices) - len(clean))
        if len(clean) < MIN_BENCHMARK_SAMPLE:
            return None, diagnostic
        return MarketPrice(model=model, storage_gb=storage, condition=condition, min_price=min(clean), median_price=round(median(clean)), avg_price=round(mean(clean)), max_price=max(clean), sample_size=len(clean), currency=currency, updated_at=datetime.now(timezone.utc)), diagnostic

    def build(self, listings: list[Listing]) -> list[MarketPrice]:
        groups: dict[tuple[str, int, str, str], list[int]] = defaultdict(list)
        for listing in listings:
            if key := self._key(listing):
                groups[key].append(listing.price)
        result: list[MarketPrice] = []
        self.diagnostics = []
        for key in sorted(groups):
            benchmark, diagnostic = self._calculate(key, groups[key])
            self.diagnostics.append(diagnostic)
            if benchmark:
                result.append(benchmark)
        return result

    def lookup_for_listing(self, listing: Listing, universe: list[Listing]) -> MarketPrice | None:
        key = self._key(listing)
        if key is None:
            return None
        comparable = [item for item in universe if (item.source, item.external_id) != (listing.source, listing.external_id)]
        return next((market for market in self.build(comparable) if (market.model, market.storage_gb, market.condition, market.currency) == key), None)
