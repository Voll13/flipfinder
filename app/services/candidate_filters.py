"""Pure candidate selection helpers for model and structured geography filters."""
from __future__ import annotations

import re

from app.models import Listing
from app.services.device_attributes import canonicalize_iphone_model


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def matches_model(listing: Listing, selected_model: str) -> bool:
    target = canonicalize_iphone_model(selected_model)
    if target is None:
        return False
    structured = canonicalize_iphone_model(listing.attributes.get("phonemodel"))
    if structured is not None:
        return structured == target
    match = re.search(r"iphone\s+\d+(?:\s+(?:mini|plus|pro(?:\s+max)?))?", listing.title, re.I)
    return bool(match and canonicalize_iphone_model(match.group(0)) == target)


def matches_location(listing: Listing, cities: list[str] | None, regions: list[str] | None) -> bool:
    selected_cities = {normalize(value) for value in cities or [] if normalize(value)}
    selected_regions = {normalize(value) for value in regions or [] if normalize(value)}
    city_ok = not selected_cities or normalize(listing.attributes.get("location_city", "")) in selected_cities
    region_ok = not selected_regions or normalize(listing.attributes.get("location_region", "")) in selected_regions
    return city_ok and region_ok
