"""Conservative normalization from generic OLX records into RentalListing."""
from __future__ import annotations

from datetime import datetime

from app.marketplaces.olx.models import OLXRawListing
from app.verticals.rental.models import RentalListing


def _location_value(location: dict[str, object], key: str) -> str | None:
    value = location.get(key)
    return " ".join(value.split()) or None if isinstance(value, str) else None


class RentalNormalizer:
    """Map only source fields verified by an OLX payload; retain all params verbatim."""

    def normalize(
        self, raw: OLXRawListing, *, first_seen_at: datetime, last_seen_at: datetime,
    ) -> RentalListing | None:
        if raw.currency != "PLN" or raw.price <= 0:
            return None
        city = _location_value(raw.raw_location, "cityName")
        # City is a core RentalListing field.  pathName is a display path, not a
        # reliable city field, so it is deliberately not used as a substitute.
        if city is None:
            return None
        return RentalListing(
            source="olx", source_listing_id=raw.source_listing_id, canonical_url=raw.canonical_url,
            title=raw.title, country_code="PL", city=city,
            district=_location_value(raw.raw_location, "districtName"),
            rent_price_pln=raw.price, published_at=raw.published_at,
            advertiser_type="private" if raw.seller_type == "private" else "agency" if raw.seller_type == "business" else None,
            description=raw.description, image_urls=list(raw.image_urls),
            main_image_url=raw.image_urls[0] if raw.image_urls else None,
            source_attributes=dict(raw.params), first_seen_at=first_seen_at, last_seen_at=last_seen_at,
        )
