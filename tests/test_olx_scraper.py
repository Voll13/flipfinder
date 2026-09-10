from __future__ import annotations

import json
from html import escape as html_escape
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import Settings
from app.exceptions import ScraperError
from app.models import Listing
from app.scrapers.olx import IPHONE_CATEGORY_URL, OLXScraper


def ad(identifier: int = 42, title: str = "Apple iPhone 15 Pro") -> dict:
    return {"id": identifier, "urlPath": f"/d/oferta/{identifier}.html", "title": title,
            "price": {"regularPrice": {"value": "900", "currencyCode": "PLN"}},
            "location": {"cityName": "Warsaw", "districtName": "Center", "regionName": "Mazovia"},
            "createdTime": "2026-09-01T10:00:00+02:00", "isBusiness": False,
            "description": "One<br>\nTwo", "photos": ["https://img/1", "https://img/1", "https://img/2"],
            "params": [{"key": "state", "normalizedValue": "used"}]}

def html(state: dict) -> str:
    value = json.dumps(json.dumps(state))
    return f'<script id="olx-init-config">window.__PRERENDERED_STATE__ = {value};</script>'

@pytest.fixture
def scraper() -> OLXScraper:
    return OLXScraper(Settings(_env_file=None, request_min_delay=0, request_max_delay=0))

def test_extract_and_map_search(scraper: OLXScraper) -> None:
    fixture = Path(__file__).parent / "fixtures" / "olx_search_minimal.html"
    listings = scraper._parse_search_html(fixture.read_text(encoding="utf-8"))
    assert len(listings) == 1
    item = listings[0]
    assert (item.external_id, item.price, item.currency) == ("9001", 1234, "PLN")
    assert item.location == "Test City"
    assert item.seller_type == "private" and item.published_at is not None
    assert item.description == "Test\ndescription" and item.photo_urls == ["https://example.test/photo.jpg"]
    assert item.attributes == {"location_city": "Test City"}


def test_public_offline_parser_and_filter_use_production_logic(scraper: OLXScraper) -> None:
    fixture = Path(__file__).parent / "fixtures" / "olx_search_minimal.html"
    listings = scraper.parse_search_html(fixture.read_text(encoding="utf-8"))
    assert scraper.filter_search_results(listings, "  IPHONE  ", price_from=1000) == listings

def test_missing_or_invalid_state_raises(scraper: OLXScraper) -> None:
    with pytest.raises(ScraperError): scraper._extract_prerendered_state("<html></html>")
    with pytest.raises(ScraperError): scraper._extract_prerendered_state('<script id="olx-init-config">window.__PRERENDERED_STATE__ = "bad";</script>')


def test_extract_state_from_chrome_view_source_save(scraper: OLXScraper) -> None:
    assignment = 'window.__PRERENDERED_STATE__ = ' + json.dumps(json.dumps({"listing": {}})) + ';'
    saved_source = f'<table><td class="line-content">{html_escape(assignment)}</td></table>'
    assert scraper._extract_prerendered_state(saved_source) == {"listing": {}}


@pytest.mark.parametrize("source", [
    '<script id="olx-init-config">no assignment</script>',
    '<script id="olx-init-config">window.__PRERENDERED_STATE__ = {bad};</script>',
    '<script id="olx-init-config">window.__PRERENDERED_STATE__ = "[]";</script>',
])
def test_invalid_embedded_state_variants(scraper: OLXScraper, source: str) -> None:
    with pytest.raises(ScraperError):
        scraper._extract_prerendered_state(source)


def test_mapping_optional_malformed_and_location(scraper: OLXScraper, caplog: pytest.LogCaptureFixture) -> None:
    record = ad(); record["title"] = "  Apple   iPhone  "; record["isBusiness"] = True
    record["location"] = {"cityName": "X", "districtName": "X", "regionName": "R"}
    item = scraper._listing_from_ad(record)
    assert item and item.title == "Apple iPhone" and item.seller_type == "business"
    assert item.location == "X, R" and item.published_at and item.published_at.tzinfo
    record["location"] = {"pathName": "Fallback path"}; record.pop("description"); record.pop("photos")
    item = scraper._listing_from_ad(record)
    assert item and item.location == "Fallback path" and item.description is None and item.photo_urls == []
    record = ad(); item = scraper._listing_from_ad(record)
    assert item and item.attributes["location_city"] == "Warsaw" and item.attributes["location_district"] == "Center" and item.attributes["location_region"] == "Mazovia"
    assert scraper._listing_from_ad({"id": 1}) is None
    malformed_price = ad(); malformed_price["price"] = {"regularPrice": None}
    assert scraper._listing_from_ad(malformed_price) is None
    assert "Skipping malformed" in caplog.text

def test_detail_and_params(scraper: OLXScraper) -> None:
    base = Listing(source="olx", external_id="42", url="https://x", title="old", price=1)
    item = scraper._parse_detail_html(html({"ad": {"ad": ad()}}), base)
    assert item.title == "Apple iPhone 15 Pro"
    record = ad(); record["params"] = [{"key": "phonemodel", "normalizedValue": "iphone-15-pro"}, {"key": "builtinmemory_phones", "normalizedValue": "128gb"}, {"key": "state", "normalizedValue": "used"}, {"key": "empty", "value": []}]
    assert scraper._parse_params(record) == {"phonemodel": "iphone-15-pro", "builtinmemory_phones": "128gb", "state": "used"}

def test_urls_and_dom_fallback(scraper: OLXScraper) -> None:
    assert scraper._build_page_url(1) == IPHONE_CATEGORY_URL
    assert scraper._build_page_url(2).endswith("?page=2")
    page = '<div data-testid="l-card" data-cy="l-card" id="7"><a data-testid="card-title-link" href="/x"> iPhone </a><p data-testid="ad-price">1 200 zł</p><p data-testid="location-date">Warsaw</p></div>'
    assert scraper._parse_search_html(page)[0].external_id == "7"


def test_dom_fallback_uses_only_unambiguous_title_model_and_storage(scraper: OLXScraper) -> None:
    page = '<div data-testid="l-card" data-cy="l-card" id="7"><a data-testid="card-title-link" href="/x">iPhone 15 Pro 256GB</a><p data-testid="ad-price">1 200 zł</p></div>'
    item = scraper.parse_search_html(page)[0]
    assert item.attributes == {"phonemodel": "iphone-15-pro", "builtinmemory_phones": "256gb"}
    assert "state" not in item.attributes


def test_dom_fallback_does_not_invent_ambiguous_storage_or_condition(scraper: OLXScraper) -> None:
    page = '<div data-testid="l-card" data-cy="l-card" id="7"><a data-testid="card-title-link" href="/x">iPhone 15 Super telefon</a><p data-testid="ad-price">1 200 zł</p></div>'
    item = scraper.parse_search_html(page)[0]
    assert "builtinmemory_phones" not in item.attributes and "state" not in item.attributes

@pytest.mark.asyncio
async def test_filters_pagination_and_dedup(scraper: OLXScraper) -> None:
    first = html({"listing": {"listing": {"ads": [ad(), ad(43, "Other")]}}})
    empty = html({"listing": {"listing": {"ads": []}}})
    scraper._request = AsyncMock(side_effect=[httpx.Response(200, text=first), httpx.Response(200, text=empty)])  # type: ignore[method-assign]
    result = await scraper.search(" iphone   15 ", price_from=800, state="PRIVATE", max_pages=3)
    assert [x.external_id for x in result] == ["42"]
    assert scraper._request.call_args_list[1].args[1].endswith("?page=2")
    with pytest.raises(ValueError): await scraper.search("x", state="bad")
    with pytest.raises(NotImplementedError): await scraper.search("x", district_id="1")


@pytest.mark.asyncio
async def test_search_boundaries_order_and_empty_stop(scraper: OLXScraper) -> None:
    page1 = html({"listing": {"listing": {"ads": [ad(2), ad(1)]}}})
    page2 = html({"listing": {"listing": {"ads": [ad(1), ad(3)]}}})
    scraper._request = AsyncMock(side_effect=[httpx.Response(200, text=page1), httpx.Response(200, text=page2)])  # type: ignore[method-assign]
    items = await scraper.search("iphone", price_to=900, max_pages=2)
    assert [x.external_id for x in items] == ["2", "1", "3"]
    assert scraper._request.call_count == 2
    scraper._request = AsyncMock(return_value=httpx.Response(200, text=html({"listing": {"listing": {"ads": []}}})))  # type: ignore[method-assign]
    assert await scraper.search("iphone", max_pages=4) == []
    assert scraper._request.call_count == 1


@pytest.mark.asyncio
async def test_price_from_business_and_fetch_details(scraper: OLXScraper) -> None:
    business = ad(9); business["isBusiness"] = True; business["price"]["regularPrice"]["value"] = 1200
    page = html({"listing": {"listing": {"ads": [business]}}})
    scraper._request = AsyncMock(return_value=httpx.Response(200, text=page))  # type: ignore[method-assign]
    assert [x.external_id for x in await scraper.search("iphone", price_from=1000, state="business")] == ["9"]
    base = Listing(source="olx", external_id="old", url="https://x", title="old", price=1)
    scraper._request = AsyncMock(return_value=httpx.Response(200, text=html({"ad": {"ad": business}})))  # type: ignore[method-assign]
    detail = await scraper.fetch_details(base)
    assert detail.external_id == "old" and detail.description and detail.photo_urls


def test_detail_fixture_and_missing_state_keep_existing(scraper: OLXScraper) -> None:
    base = Listing(source="olx", external_id="9001", url="https://x", title="old", price=1)
    fixture = Path(__file__).parent / "fixtures" / "olx_detail_minimal.html"
    detail = scraper._parse_detail_html(fixture.read_text(encoding="utf-8"), base)
    assert detail.title == "Synthetic iPhone" and detail.price == 1234
    assert scraper._parse_detail_html("<html></html>", base) is base
