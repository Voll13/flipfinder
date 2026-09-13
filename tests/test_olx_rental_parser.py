from datetime import datetime, timezone
from decimal import Decimal
from html import escape
import json
from pathlib import Path

import pytest

from app.config import Settings
from app.marketplaces.olx.embedded_state import extract_prerendered_state
from app.marketplaces.olx.models import extract_search_raw_listings
from app.marketplaces.olx.rental_parser import OLXRentalParser
from app.scrapers.olx import OLXScraper


def html_from_state(state: dict) -> str:
    assignment = "window.__PRERENDERED_STATE__ = " + json.dumps(json.dumps(state)) + ";"
    return f'<script id="olx-init-config">{assignment}</script>'


@pytest.fixture
def synthetic_state() -> dict:
    return json.loads(Path("tests/fixtures/olx_rental_raw_synthetic.json").read_text(encoding="utf-8"))


def ad(state: dict) -> dict:
    return state["listing"]["listing"]["ads"][0]


def params(record: dict) -> dict[str, dict]:
    return {item["key"]: item for item in record["params"]}


def listing(state: dict):
    return OLXRentalParser().parse_search_html(html_from_state(state), datetime(2026, 9, 10, tzinfo=timezone.utc))[0]


def test_shared_embedded_state_is_backward_compatible_with_iphone_scraper(synthetic_state: dict):
    html = html_from_state(synthetic_state)
    legacy = OLXScraper(Settings(_env_file=None))._extract_prerendered_state(html)
    assert extract_prerendered_state(html) == legacy == synthetic_state
    saved_source = f'<table><td class="line-content">{escape("window.__PRERENDERED_STATE__ = " + json.dumps(json.dumps(synthetic_state)) + ";")}</td></table>'
    assert extract_prerendered_state(saved_source) == synthetic_state


def test_raw_contract_keeps_coordinates_and_compact_multivalue_params(synthetic_state: dict):
    raw = extract_search_raw_listings(html_from_state(synthetic_state))[0]
    assert raw.source_listing_id == "rental-100" and raw.price == 3300 and raw.currency == "PLN"
    assert raw.latitude == Decimal("50.675") and raw.longitude == Decimal("17.92")
    assert raw.params["parking"] == "w garażu, przynależne na ulicy"
    assert raw.image_urls == ["https://images.example/rental-1.jpg", "https://images.example/rental-2.jpg"]


def test_normalizes_verified_search_fields_without_inventing_address_or_property_type(synthetic_state: dict):
    item = listing(synthetic_state)
    assert item.city == "Opole" and item.district is None and item.address_text is None
    assert item.latitude == Decimal("50.675") and item.longitude == Decimal("17.92")
    assert item.rent_price_pln == 3300 and item.admin_fee_pln == 650 and item.known_monthly_total_pln == 3950
    assert item.rooms == Decimal("2") and item.area_m2 == Decimal("55.5") and item.floor_label == "2"
    assert item.furnished is True and item.elevator is True and item.parking is True and item.pets_policy == "not_allowed"
    assert item.advertiser_type == "agency" and item.property_type is None and item.total_floors is None
    assert item.source_attributes["builttype"] == "apartamentowiec"
    assert item.main_image_url == item.image_urls[0] and item.published_at and item.published_at.tzinfo


@pytest.mark.parametrize(("raw", "expected"), [("one", Decimal("1")), ("two", Decimal("2")), ("three", Decimal("3")), ("four", None), ("2", Decimal("2"))])
def test_rooms_mapping_is_structured_only(synthetic_state: dict, raw: str, expected: Decimal | None):
    params(ad(synthetic_state))["rooms"]["normalizedValue"] = raw
    assert listing(synthetic_state).rooms == expected


@pytest.mark.parametrize(("raw", "expected"), [("36", Decimal("36")), ("55.5", Decimal("55.5")), ("55,5", Decimal("55.5")), ("not-a-number", None)])
def test_area_mapping_preserves_decimal_precision(synthetic_state: dict, raw: str, expected: Decimal | None):
    params(ad(synthetic_state))["m"]["normalizedValue"] = raw
    assert listing(synthetic_state).area_m2 == expected


@pytest.mark.parametrize(("raw", "expected"), [("floor_0", "0"), ("floor_2", "2"), ("floor_-1", "-1"), ("parter", None)])
def test_floor_mapping_accepts_only_verified_prefix(synthetic_state: dict, raw: str, expected: str | None):
    params(ad(synthetic_state))["floor_select"]["normalizedValue"] = raw
    assert listing(synthetic_state).floor_label == expected


def test_optional_boolean_and_admin_fee_mappings(synthetic_state: dict):
    source = params(ad(synthetic_state))
    source["furniture"]["normalizedValue"] = "no"
    source["winda"]["normalizedValue"] = "Nie"
    source["pets"]["normalizedValue"] = "Tak"
    source["parking"]["normalizedValue"] = ["brak"]
    source["rent"]["normalizedValue"] = " 1 200 "
    item = listing(synthetic_state)
    assert (item.furnished, item.elevator, item.pets_policy, item.parking, item.admin_fee_pln) == (False, False, "allowed", False, 1200)


def test_missing_optional_fields_are_unknown_not_false(synthetic_state: dict):
    record = ad(synthetic_state)
    record["params"] = [item for item in record["params"] if item["key"] not in {"rent", "furniture", "winda", "pets", "parking"}]
    item = listing(synthetic_state)
    assert item.admin_fee_pln is None and item.furnished is None and item.elevator is None
    assert item.parking is None and item.pets_policy is None


@pytest.mark.parametrize(("coordinate", "expected"), [("50.1", Decimal("50.1")), ("bad", None), (None, None)])
def test_coordinates_are_typed_or_none(synthetic_state: dict, coordinate: object, expected: Decimal | None):
    ad(synthetic_state)["map"] = {"lat": coordinate, "lon": coordinate}
    item = listing(synthetic_state)
    assert item.latitude == expected and item.longitude == expected


def test_private_seller_and_missing_optional_data_do_not_crash(synthetic_state: dict):
    record = ad(synthetic_state)
    record["isBusiness"] = False
    record.pop("createdTime")
    record.pop("map")
    record.pop("photos")
    record["location"] = {"cityName": "Opole"}
    item = listing(synthetic_state)
    assert item.advertiser_type == "private" and item.published_at is None
    assert item.latitude is None and item.longitude is None and item.image_urls == [] and item.main_image_url is None


def test_invalid_or_cityless_ads_are_skipped_without_crashing(synthetic_state: dict):
    record = ad(synthetic_state)
    record["price"] = {"regularPrice": None}
    assert OLXRentalParser().parse_search_html(html_from_state(synthetic_state), datetime.now(timezone.utc)) == []
    record["price"] = {"regularPrice": {"value": "3300", "currencyCode": "PLN"}}
    record["location"] = {"regionName": "opolskie"}
    assert OLXRentalParser().parse_search_html(html_from_state(synthetic_state), datetime.now(timezone.utc)) == []
