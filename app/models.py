from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Listing(BaseModel):
    source: Literal["olx", "allegro"]
    external_id: str
    url: str
    title: str
    price: int
    currency: str = "PLN"

    location: str | None = None
    seller_type: str | None = None
    published_at: datetime | None = None

    description: str | None = None
    photo_urls: list[str] = Field(default_factory=list)
    attributes: dict[str, str] = Field(default_factory=dict)

    id: int | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    is_active: bool = True

    @field_validator("external_id")
    @classmethod
    def _external_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("external_id must not be empty")
        return v

    @field_validator("url")
    @classmethod
    def _url_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("url must not be empty")
        return v

    @field_validator("title")
    @classmethod
    def _title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("title must not be empty")
        return v

    @field_validator("price")
    @classmethod
    def _price_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("price must be >= 0")
        return v


class DeviceInfo(BaseModel):
    model: str | None = None
    storage_gb: int | None = None
    battery_health: int | None = None
    condition: str | None = None
    color: str | None = None

    has_box: bool | None = None
    has_receipt: bool | None = None
    has_warranty: bool | None = None

    damaged: bool | None = None
    screen_damaged: bool | None = None

    icloud_locked: bool | None = None
    operator_locked: bool | None = None

    sim_type: str | None = None

    @field_validator("battery_health")
    @classmethod
    def _battery_health_range(cls, v: int | None) -> int | None:
        if v is not None and not 0 <= v <= 100:
            raise ValueError("battery_health must be between 0 and 100")
        return v

    @field_validator("storage_gb")
    @classmethod
    def _storage_positive(cls, v: int | None) -> int | None:
        if v is not None and v <= 0:
            raise ValueError("storage_gb must be > 0")
        return v


class MarketPrice(BaseModel):
    model: str
    storage_gb: int
    condition: str

    min_price: int
    avg_price: int
    max_price: int
    median_price: int | None = None

    sample_size: int = 0
    currency: str = "PLN"
    updated_at: datetime | None = None

    @field_validator("avg_price", "min_price", "max_price")
    @classmethod
    def _prices_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("price must be >= 0")
        return v

    @field_validator("sample_size")
    @classmethod
    def _sample_size_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("sample_size must be >= 0")
        return v

    @field_validator("avg_price")
    @classmethod
    def _avg_gte_min(cls, v: int, info) -> int:
        min_price = info.data.get("min_price")
        if min_price is not None and v < min_price:
            raise ValueError(f"avg_price ({v}) must be >= min_price ({min_price})")
        return v

    @field_validator("max_price")
    @classmethod
    def _max_gte_avg(cls, v: int, info) -> int:
        avg_price = info.data.get("avg_price")
        if avg_price is not None and v < avg_price:
            raise ValueError(f"max_price ({v}) must be >= avg_price ({avg_price})")
        return v


class AIAnalysis(BaseModel):
    device_info: DeviceInfo

    estimated_resale_price: int
    resale_confidence: float = Field(ge=0.0, le=1.0)

    recommended_buy_price: int | None = None

    red_flags: list[str] = Field(default_factory=list)
    positive_signals: list[str] = Field(default_factory=list)

    fraud_risk: float = Field(ge=0.0, le=1.0)

    summary: str

    @field_validator("estimated_resale_price")
    @classmethod
    def _resale_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("estimated_resale_price must be >= 0")
        return v

    @field_validator("recommended_buy_price")
    @classmethod
    def _buy_price_non_negative(cls, v: int | None) -> int | None:
        if v is not None and v < 0:
            raise ValueError("recommended_buy_price must be >= 0")
        return v


class FlipEvaluation(BaseModel):
    # Missing in historical JSON means version 1, preserving backward reads.
    scoring_version: int = 1
    flip_score: float = Field(ge=0.0, le=100.0)

    estimated_profit: int
    margin_pct: float

    fees_estimate: int = 0

    resale_price_used: int | None = None
    resale_source: str | None = None
    resale_confidence_used: float | None = Field(default=None, ge=0.0, le=0.0 + 1.0)
    market_sample_size: int | None = Field(default=None, ge=0)

    is_flip_candidate: bool

    reasons: list[str] = Field(default_factory=list)

    @field_validator("fees_estimate")
    @classmethod
    def _fees_non_negative(cls, v: int) -> int:
        if v < 0:
            raise ValueError("fees_estimate must be >= 0")
        return v
