from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.verticals.rental.models import RentalListing


def rental(**changes):
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    data = {
        "source": "olx", "source_listing_id": "123", "canonical_url": "https://www.olx.pl/d/oferta/123",
        "title": "Mieszkanie w Opolu", "city": "Opole", "rent_price_pln": 3300,
        "first_seen_at": now, "last_seen_at": now,
    }
    data.update(changes)
    return RentalListing(**data)


def test_rental_listing_validates_core_fields_and_preserves_unknown_published_at():
    item = rental()
    assert item.country_code == "PL"
    assert item.published_at is None
    with pytest.raises(ValidationError):
        rental(source_listing_id=" ")
    with pytest.raises(ValidationError):
        rental(rent_price_pln=0)


def test_derived_price_per_m2_and_known_monthly_total():
    item = rental(area_m2=Decimal("55"), admin_fee_pln=650)
    assert item.price_per_m2_pln == Decimal("60")
    assert item.known_monthly_total_pln == 3950


def test_missing_or_invalid_area_and_unknown_admin_fee_do_not_infer_values():
    assert rental().price_per_m2_pln is None
    assert rental(area_m2=Decimal("0")).price_per_m2_pln is None
    assert rental(area_m2=Decimal("-1")).price_per_m2_pln is None
    assert rental().known_monthly_total_pln is None
