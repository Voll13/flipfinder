from app.models import Listing
from app.services.candidate_filters import matches_location, matches_model


def item(**changes):
    data = {"source":"olx", "external_id":"1", "url":"https://x", "title":"iPhone 15 Pro 128GB", "price":2000, "attributes":{"phonemodel":"iphone-15-pro", "location_city":"Opole", "location_region":"opolskie", "location_district":"Centrum"}}
    data.update(changes)
    return Listing(**data)


def test_structured_model_is_exact_and_title_fallback_is_exact():
    assert matches_model(item(), "iPhone 15 Pro")
    assert not matches_model(item(), "iPhone 15 Pro Max")
    fallback = item(attributes={}, title="Oferta iPhone 15 Pro 128 GB")
    assert matches_model(fallback, "iPhone 15 Pro") and not matches_model(fallback, "iPhone 15 Pro Max")


def test_location_filters_are_or_within_and_between_categories():
    listing = item()
    assert matches_location(listing, ["Wroclaw", " Opole "], None)
    assert matches_location(listing, None, ["opolskie"])
    assert matches_location(listing, ["Opole"], ["opolskie"])
    assert not matches_location(listing, ["Opole"], ["dolnoslaskie"])
    assert not matches_location(item(attributes={}), ["Opole"], None)
