"""Typed domain contracts for the future Rental vertical."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator


PetsPolicy = Literal["allowed", "not_allowed", "negotiable"]
AdvertiserType = Literal["private", "agency"]
PublicationStatus = Literal["pending", "sent", "failed", "uncertain"]


class RentalListing(BaseModel):
    """One rental offer observed by FlipFinder, independent of publication state."""

    source: str
    source_listing_id: str
    canonical_url: str
    title: str
    country_code: str = "PL"
    city: str
    rent_price_pln: int = Field(gt=0)
    first_seen_at: datetime
    last_seen_at: datetime
    is_active: bool = True

    published_at: datetime | None = None
    district: str | None = None
    address_text: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    property_type: str | None = None
    rooms: Decimal | None = Field(default=None, gt=0)
    area_m2: Decimal | None = None
    floor_label: str | None = None
    total_floors: int | None = Field(default=None, ge=0)
    admin_fee_pln: int | None = Field(default=None, ge=0)
    utilities_text: str | None = None
    deposit_pln: int | None = Field(default=None, ge=0)
    furnished: bool | None = None
    balcony: bool | None = None
    elevator: bool | None = None
    parking: bool | None = None
    pets_policy: PetsPolicy | None = None
    advertiser_type: AdvertiserType | None = None
    agency_name: str | None = None
    description: str | None = None
    image_urls: list[str] = Field(default_factory=list)
    main_image_url: str | None = None
    source_attributes: dict[str, str] = Field(default_factory=dict)

    @field_validator("source", "source_listing_id", "canonical_url", "title", "city")
    @classmethod
    def _required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be empty")
        return value

    @field_validator("country_code")
    @classmethod
    def _country_code(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 2:
            raise ValueError("country_code must be a two-letter code")
        return value

    @computed_field
    @property
    def price_per_m2_pln(self) -> Decimal | None:
        """Return the source rent divided by area; never infer an unavailable area."""
        if self.area_m2 is None or self.area_m2 <= 0:
            return None
        return Decimal(self.rent_price_pln) / self.area_m2

    @computed_field
    @property
    def known_monthly_total_pln(self) -> int | None:
        """Known rent plus administrative fee, excluding unknown utilities."""
        if self.admin_fee_pln is None:
            return None
        return self.rent_price_pln + self.admin_fee_pln


class RentalProfile(BaseModel):
    """Persistent city/search configuration without Telegram credentials."""

    key: str
    marketplace: str
    vertical: Literal["rental"] = "rental"
    country_code: str = "PL"
    source_city: str
    display_name_ru: str
    search_url: str
    destination_key: str
    enabled: bool = True
    bootstrap_completed_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @field_validator("key", "marketplace", "source_city", "display_name_ru", "search_url", "destination_key")
    @classmethod
    def _profile_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be empty")
        return value

    @field_validator("country_code")
    @classmethod
    def _profile_country_code(cls, value: str) -> str:
        value = value.strip().upper()
        if len(value) != 2:
            raise ValueError("country_code must be a two-letter code")
        return value


class RentalPublication(BaseModel):
    """Persistent delivery state for one listing and one destination."""

    id: int | None = None
    rental_listing_id: int
    destination_key: str
    status: PublicationStatus = "pending"
    telegram_message_id: int | None = None
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None = None
    last_error: str | None = None
