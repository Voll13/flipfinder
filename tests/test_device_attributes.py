import pytest

from app.services.device_attributes import canonicalize_iphone_model, canonicalize_storage


@pytest.mark.parametrize(("raw", "expected"), [("iphone-15-pro", "iPhone 15 Pro"), ("iphone-15-pro-max", "iPhone 15 Pro Max"), ("iphone-13-mini", "iPhone 13 Mini"), ("iphone-14-plus", "iPhone 14 Plus"), ("iphone-se", "iPhone SE"), ("iphone-16pro", "iPhone 16 Pro")])
def test_canonicalize_iphone_model(raw, expected):
    assert canonicalize_iphone_model(raw) == expected


@pytest.mark.parametrize(("raw", "expected"), [("128gb", 128), ("1tb", 1024), ("others", None)])
def test_canonicalize_storage(raw, expected):
    assert canonicalize_storage(raw) == expected
