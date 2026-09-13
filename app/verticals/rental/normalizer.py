"""Conservative normalization from generic OLX records into RentalListing."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
import re

from app.marketplaces.olx.models import OLXRawListing
from app.verticals.rental.models import RentalListing


def _location_value(location: dict[str, object], key: str) -> str | None:
    value = location.get(key)
    return " ".join(value.split()) or None if isinstance(value, str) else None


_FLOOR_RE = re.compile(r"floor_(-?\d+)$")
_ROOMS = {"one": Decimal("1"), "two": Decimal("2"), "three": Decimal("3")}


def _param(raw: OLXRawListing, key: str) -> str | None:
    value = raw.params.get(key)
    return " ".join(value.split()) if value else None


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        result = Decimal(value.replace("\u00a0", "").replace(" ", "").replace(",", "."))
    except InvalidOperation:
        return None
    return result if result.is_finite() and result > 0 else None


def _rooms(value: str | None) -> Decimal | None:
    if value is None:
        return None
    normalized = value.casefold()
    return _ROOMS.get(normalized) or _decimal(normalized)


def _floor(value: str | None) -> str | None:
    match = _FLOOR_RE.fullmatch(value or "")
    return match.group(1) if match else None


def _integer(value: str | None) -> int | None:
    numeric = _decimal(value)
    return int(numeric) if numeric is not None and numeric == numeric.to_integral_value() else None


def _boolean(value: str | None, *, yes: str, no: str) -> bool | None:
    normalized = value.casefold() if value else None
    if normalized == yes:
        return True
    if normalized == no:
        return False
    return None


def _parking(value: str | None) -> bool | None:
    if value is None:
        return None
    return False if value.casefold() == "brak" else True


def _pets(value: str | None) -> str | None:
    normalized = value.casefold() if value else None
    return {"tak": "allowed", "nie": "not_allowed"}.get(normalized)


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
            latitude=raw.latitude, longitude=raw.longitude,
            rent_price_pln=raw.price, published_at=raw.published_at,
            rooms=_rooms(_param(raw, "rooms")), area_m2=_decimal(_param(raw, "m")),
            floor_label=_floor(_param(raw, "floor_select")), admin_fee_pln=_integer(_param(raw, "rent")),
            furnished=_boolean(_param(raw, "furniture"), yes="yes", no="no"),
            elevator=_boolean(_param(raw, "winda"), yes="tak", no="nie"),
            parking=_parking(_param(raw, "parking")), pets_policy=_pets(_param(raw, "pets")),
            advertiser_type="private" if raw.seller_type == "private" else "agency" if raw.seller_type == "business" else None,
            description=raw.description, image_urls=list(raw.image_urls),
            main_image_url=raw.image_urls[0] if raw.image_urls else None,
            source_attributes=dict(raw.params), first_seen_at=first_seen_at, last_seen_at=last_seen_at,
        )
