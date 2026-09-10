"""Marketplace-level OLX ad contract with no product-vertical knowledge."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from app.exceptions import ScraperError
from app.marketplaces.olx.embedded_state import extract_prerendered_state


logger = logging.getLogger(__name__)
SellerType = Literal["private", "business"]


@dataclass(frozen=True)
class OLXRawListing:
    source_listing_id: str
    canonical_url: str
    title: str
    price: int
    currency: str
    location_text: str | None
    raw_location: dict[str, Any]
    description: str | None
    image_urls: list[str]
    seller_type: SellerType | None
    published_at: datetime | None
    params: dict[str, str]


def _text(value: object) -> str | None:
    return " ".join(value.split()) or None if isinstance(value, str) else None


def _price(ad: dict[str, Any]) -> tuple[int, str] | None:
    regular = ad.get("price", {}).get("regularPrice", {}) if isinstance(ad.get("price"), dict) else {}
    if not isinstance(regular, dict):
        return None
    value = regular.get("value")
    currency = _text(regular.get("currencyCode")) or "PLN"
    if isinstance(value, bool):
        return None
    try:
        number = int(float(value))
        integral = float(value).is_integer()
    except (TypeError, ValueError):
        return None
    return (number, currency) if number >= 0 and integral else None


def _location(ad: dict[str, Any]) -> tuple[str | None, dict[str, Any]]:
    raw = ad.get("location")
    if not isinstance(raw, dict):
        return None, {}
    values = list(dict.fromkeys(value for value in (_text(raw.get(key)) for key in ("cityName", "districtName", "regionName")) if value))
    return (", ".join(values) if values else _text(raw.get("pathName"))), dict(raw)


def _published_at(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if isinstance(value, str) else None
    except ValueError:
        logger.warning("Ignoring malformed OLX createdTime")
        return None


def _description(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    soup = BeautifulSoup(value, "html.parser")
    for tag in soup.find_all(["br", "p", "li"]):
        tag.insert_after("\n")
    return "\n".join(
        line for line in (" ".join(line.split()) for line in soup.get_text("\n").splitlines()) if line
    ) or None


def _images(ad: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for url in ad.get("photos", []) if isinstance(ad.get("photos"), list) else []:
        if isinstance(url, str) and url.strip() and url not in result:
            result.append(url)
    return result


def _params(ad: dict[str, Any]) -> dict[str, str]:
    if not isinstance(ad.get("params"), list):
        return {}
    result: dict[str, str] = {}
    for item in ad["params"]:
        if not isinstance(item, dict) or not isinstance(item.get("key"), str):
            continue
        key = _text(item["key"])
        value = _text(item.get("normalizedValue", item.get("value")))
        if key and value:
            result[key] = value
    return result


def raw_listing_from_ad(ad: dict[str, Any]) -> OLXRawListing | None:
    """Extract only source-level OLX fields; malformed ads are safely skipped."""
    ident = ad.get("id")
    title = _text(ad.get("title"))
    url = _text(ad.get("url")) or _text(ad.get("urlPath"))
    price = _price(ad)
    if ident is None or not title or not url or price is None:
        logger.warning("Skipping malformed OLX ad")
        return None
    location_text, raw_location = _location(ad)
    business = ad.get("isBusiness")
    seller_type: SellerType | None = "business" if business is True else "private" if business is False else None
    return OLXRawListing(
        source_listing_id=str(ident), canonical_url=urljoin("https://www.olx.pl/", url), title=title,
        price=price[0], currency=price[1], location_text=location_text, raw_location=raw_location,
        description=_description(ad.get("description")), image_urls=_images(ad), seller_type=seller_type,
        published_at=_published_at(ad.get("createdTime")), params=_params(ad),
    )


def extract_search_raw_listings(html: str) -> list[OLXRawListing]:
    """Extract marketplace-level listing records from a saved OLX search page."""
    ads = extract_prerendered_state(html).get("listing", {}).get("listing", {}).get("ads")
    if not isinstance(ads, list):
        raise ScraperError("OLX search ads are missing")
    return [raw for ad in ads if isinstance(ad, dict) and (raw := raw_listing_from_ad(ad))]
