from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path

import pytest

from app.marketplaces.olx.embedded_state import extract_prerendered_state
from app.marketplaces.olx.models import extract_search_raw_listings
from app.marketplaces.olx.rental_parser import OLXRentalParser
from app.scrapers.olx import OLXScraper
from app.config import Settings


def html_from_state(state: dict) -> str:
    assignment = "window.__PRERENDERED_STATE__ = " + json.dumps(json.dumps(state)) + ";"
    return f'<script id="olx-init-config">{assignment}</script>'


@pytest.fixture
def synthetic_state() -> dict:
    path = Path("tests/fixtures/olx_rental_raw_synthetic.json")
    return json.loads(path.read_text(encoding="utf-8"))


def test_shared_embedded_state_is_backward_compatible_with_iphone_scraper(synthetic_state: dict):
    html = html_from_state(synthetic_state)
    legacy = OLXScraper(Settings(_env_file=None))._extract_prerendered_state(html)
    assert extract_prerendered_state(html) == legacy == synthetic_state
    saved_source = f'<table><td class="line-content">{escape("window.__PRERENDERED_STATE__ = " + json.dumps(json.dumps(synthetic_state)) + ";")}</td></table>'
    assert extract_prerendered_state(saved_source) == synthetic_state


def test_raw_olx_contract_extracts_only_marketplace_fields(synthetic_state: dict):
    raw = extract_search_raw_listings(html_from_state(synthetic_state))[0]
    assert raw.source_listing_id == "rental-100"
    assert raw.price == 3300 and raw.currency == "PLN"
    assert raw.location_text == "Opole, Śródmieście, opolskie"
    assert raw.seller_type == "business" and raw.published_at and raw.published_at.tzinfo
    assert raw.image_urls == ["https://images.example/rental-1.jpg", "https://images.example/rental-2.jpg"]
    assert raw.params["unverified_area"] == "55,5 m²"


def test_offline_rental_pipeline_normalizes_confirmed_fields_and_preserves_params(synthetic_state: dict):
    observed = datetime(2026, 9, 10, 16, 20, tzinfo=timezone.utc)
    listing = OLXRentalParser().parse_search_html(html_from_state(synthetic_state), observed)[0]
    assert listing.source == "olx" and listing.source_listing_id == "rental-100"
    assert listing.city == "Opole" and listing.district == "Śródmieście"
    assert listing.rent_price_pln == 3300 and listing.advertiser_type == "agency"
    assert listing.main_image_url == listing.image_urls[0]
    assert listing.source_attributes["unverified_rooms"] == "2 pokoje"
    assert listing.published_at == datetime.fromisoformat("2026-09-10T16:18:00+02:00")
    assert listing.first_seen_at == observed and listing.last_seen_at == observed


def test_unverified_rental_params_are_not_guessed_from_synthetic_payload(synthetic_state: dict):
    listing = OLXRentalParser().parse_search_html(html_from_state(synthetic_state), datetime.now(timezone.utc))[0]
    assert listing.area_m2 is None and listing.rooms is None and listing.floor_label is None
    assert listing.furnished is None and listing.balcony is None and listing.elevator is None and listing.parking is None
    assert listing.pets_policy is None and listing.admin_fee_pln is None and listing.deposit_pln is None


@pytest.mark.parametrize("value", ["55 m²", "55,5 m²", "55.5 m²"])
def test_unverified_area_values_remain_available_without_locale_assumptions(synthetic_state: dict, value: str):
    synthetic_state["listing"]["listing"]["ads"][0]["params"][0]["normalizedValue"] = value
    listing = OLXRentalParser().parse_search_html(html_from_state(synthetic_state), datetime.now(timezone.utc))[0]
    assert listing.area_m2 is None
    assert listing.source_attributes["unverified_area"] == value


def test_missing_optional_data_and_published_time_do_not_crash_or_replace_semantics(synthetic_state: dict):
    ad = synthetic_state["listing"]["listing"]["ads"][0]
    ad.pop("createdTime")
    ad["location"] = {"cityName": "Opole"}
    ad.pop("photos")
    ad["params"] = [{"key": "unsupported", "normalizedValue": "value"}, {"key": "bad", "value": []}]
    observed = datetime(2026, 9, 10, tzinfo=timezone.utc)
    listing = OLXRentalParser().parse_search_html(html_from_state(synthetic_state), observed)[0]
    assert listing.published_at is None and listing.first_seen_at == observed
    assert listing.district is None and listing.image_urls == [] and listing.main_image_url is None
    assert listing.source_attributes == {"unsupported": "value"}


def test_invalid_or_cityless_ads_are_skipped_without_crashing(synthetic_state: dict):
    ad = synthetic_state["listing"]["listing"]["ads"][0]
    ad["price"] = {"regularPrice": None}
    assert OLXRentalParser().parse_search_html(html_from_state(synthetic_state), datetime.now(timezone.utc)) == []
    ad["price"] = {"regularPrice": {"value": "3300", "currencyCode": "PLN"}}
    ad["location"] = {"districtName": "Śródmieście"}
    assert OLXRentalParser().parse_search_html(html_from_state(synthetic_state), datetime.now(timezone.utc)) == []


def test_zero_price_or_non_pln_ads_are_skipped_without_validation_errors(synthetic_state: dict):
    ad = synthetic_state["listing"]["listing"]["ads"][0]
    ad["price"] = {"regularPrice": {"value": "0", "currencyCode": "PLN"}}
    assert OLXRentalParser().parse_search_html(html_from_state(synthetic_state), datetime.now(timezone.utc)) == []
    ad["price"] = {"regularPrice": {"value": "3300", "currencyCode": "EUR"}}
    assert OLXRentalParser().parse_search_html(html_from_state(synthetic_state), datetime.now(timezone.utc)) == []
