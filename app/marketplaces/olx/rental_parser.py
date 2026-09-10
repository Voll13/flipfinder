"""Offline OLX Rental parsing path: HTML to raw ad to RentalListing."""
from __future__ import annotations

from datetime import datetime, timezone

from app.marketplaces.olx.models import OLXRawListing, extract_search_raw_listings
from app.verticals.rental.models import RentalListing
from app.verticals.rental.normalizer import RentalNormalizer


class OLXRentalParser:
    """Small vertical adapter that leaves acquisition and delivery outside this milestone."""

    def __init__(self, normalizer: RentalNormalizer | None = None) -> None:
        self._normalizer = normalizer or RentalNormalizer()

    def parse_raw_search_html(self, html: str) -> list[OLXRawListing]:
        return extract_search_raw_listings(html)

    def parse_search_html(self, html: str, observed_at: datetime | None = None) -> list[RentalListing]:
        seen_at = observed_at or datetime.now(timezone.utc)
        return [
            listing
            for raw in self.parse_raw_search_html(html)
            if (listing := self._normalizer.normalize(raw, first_seen_at=seen_at, last_seen_at=seen_at)) is not None
        ]
