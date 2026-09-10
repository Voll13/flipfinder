"""Canonical display and parsing helpers for marketplace device attributes."""
from __future__ import annotations

import re

_MODEL_RE = re.compile(r"^iphone[-\s]?(?:(\d+)[-\s]?(mini|plus|pro(?:[-\s]?max)?)?|se)$", re.I)
_STORAGE_RE = re.compile(r"^(\d+)\s*(gb|tb)$", re.I)


def canonicalize_iphone_model(value: str | None) -> str | None:
    if not value:
        return None
    match = _MODEL_RE.fullmatch(value.strip().replace("_", "-"))
    if not match:
        return None
    number, variant = match.groups()
    if number is None:
        return "iPhone SE"
    suffix = {"mini": " Mini", "plus": " Plus", "pro": " Pro", "pro-max": " Pro Max", "promax": " Pro Max"}.get((variant or "").replace(" ", "").casefold(), "")
    return f"iPhone {number}{suffix}"


def canonicalize_storage(value: str | None) -> int | None:
    if not value:
        return None
    match = _STORAGE_RE.fullmatch(value.strip().casefold())
    if not match:
        return None
    amount, unit = match.groups()
    return int(amount) * (1024 if unit == "tb" else 1)


def display_structured_attributes(attributes: dict[str, str]) -> list[tuple[str, str]]:
    model = canonicalize_iphone_model(attributes.get("phonemodel"))
    storage = canonicalize_storage(attributes.get("builtinmemory_phones"))
    values: list[tuple[str, str]] = []
    for label, value in (("Model", model), ("Storage", f"{storage} GB" if storage else None), ("State", attributes.get("state")), ("Color", attributes.get("coloriphone")), ("Charger", attributes.get("phonecharger")), ("Guarantee", attributes.get("guarantee"))):
        if value:
            values.append((label, value))
    return values
