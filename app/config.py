from __future__ import annotations

from typing import Any

from pydantic import field_validator, model_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    DotEnvSettingsSource,
    EnvSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)


class _CommaSplitEnvSource(EnvSettingsSource):
    """Env source that handles comma-separated strings for list[str] fields."""

    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        if field_name == "search_queries" and isinstance(value, str):
            return [q.strip() for q in value.split(",") if q.strip()]
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class _CommaSplitDotEnvSource(DotEnvSettingsSource):
    """Apply the same comma-separated list support to the .env file."""

    def prepare_field_value(
        self, field_name: str, field: FieldInfo, value: Any, value_is_complex: bool
    ) -> Any:
        if field_name == "search_queries" and isinstance(value, str):
            return [q.strip() for q in value.split(",") if q.strip()]
        return super().prepare_field_value(field_name, field, value, value_is_complex)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ──────────────────────────────────────────
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # ── Telegram ─────────────────────────────────────
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    # ── Storage ──────────────────────────────────────
    database_path: str = "data/flip_finder.db"

    # ── Network ──────────────────────────────────────
    http_proxy: str | None = None
    request_min_delay: float = 2.0
    request_max_delay: float = 6.0
    max_concurrent_requests: int = 2
    request_timeout: float = 30.0

    # ── Scraping ─────────────────────────────────────
    search_queries: list[str] = ["iPhone 13", "iPhone 14", "iPhone 15", "iPhone 16"]
    search_max_pages: int = 3
    max_buy_price_pln: int = 5000
    min_sanity_price_pln: int = 100

    # ── Scoring ──────────────────────────────────────
    min_flip_score: float = 70.0
    min_margin_pct: float = 15.0
    max_fraud_risk: float = 0.3
    marketplace_fee_pct: float = 0.0

    # ── Market data ──────────────────────────────────
    market_prices_path: str = "data/market_prices.json"
    market_lookback_hours: int = 72
    monitor_interval_minutes: int = 15
    # Space sequential extraction calls for providers such as Groq.  This is
    # deliberately applied by the pipeline only between actual AI requests.
    ai_request_delay_seconds: float = 4.0

    # ── Logging ──────────────────────────────────────
    log_level: str = "INFO"

    # ── Sources ──────────────────────────────────────

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            _CommaSplitEnvSource(settings_cls),
            _CommaSplitDotEnvSource(
                settings_cls,
                env_file=dotenv_settings.env_file,
                env_file_encoding=dotenv_settings.env_file_encoding,
            ),
            file_secret_settings,
        )

    # ── Validators ───────────────────────────────────

    @field_validator(
        "openai_api_key", "telegram_bot_token", "telegram_chat_id", "http_proxy",
        mode="before",
    )
    @classmethod
    def _blank_optional_strings_are_none(cls, value: Any) -> Any:
        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def _validate_ranges(self) -> Settings:
        if self.request_min_delay < 0:
            raise ValueError("request_min_delay must be >= 0")

        if self.request_max_delay < self.request_min_delay:
            raise ValueError(
                f"request_max_delay ({self.request_max_delay}) "
                f"must be >= request_min_delay ({self.request_min_delay})"
            )

        if self.max_concurrent_requests < 1:
            raise ValueError("max_concurrent_requests must be >= 1")

        if self.search_max_pages < 1:
            raise ValueError("search_max_pages must be >= 1")

        if self.max_buy_price_pln <= self.min_sanity_price_pln:
            raise ValueError(
                f"max_buy_price_pln ({self.max_buy_price_pln}) "
                f"must be > min_sanity_price_pln ({self.min_sanity_price_pln})"
            )

        if not 0 <= self.min_flip_score <= 100:
            raise ValueError("min_flip_score must be between 0 and 100")

        if self.min_margin_pct < 0:
            raise ValueError("min_margin_pct must be >= 0")

        if not 0 <= self.max_fraud_risk <= 1:
            raise ValueError("max_fraud_risk must be between 0 and 1")

        if self.marketplace_fee_pct < 0:
            raise ValueError("marketplace_fee_pct must be >= 0")

        if self.market_lookback_hours < 1:
            raise ValueError("market_lookback_hours must be >= 1")
        if not 5 <= self.monitor_interval_minutes <= 1440:
            raise ValueError("monitor_interval_minutes must be between 5 and 1440")
        if self.ai_request_delay_seconds < 0:
            raise ValueError("ai_request_delay_seconds must be >= 0")

        return self
