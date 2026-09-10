from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import Settings


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all app-related env vars so tests don't depend on user environment."""
    env_keys = [
        "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
        "DATABASE_PATH",
        "HTTP_PROXY",
        "REQUEST_MIN_DELAY", "REQUEST_MAX_DELAY",
        "MAX_CONCURRENT_REQUESTS", "REQUEST_TIMEOUT",
        "SEARCH_QUERIES", "SEARCH_MAX_PAGES",
        "MAX_BUY_PRICE_PLN", "MIN_SANITY_PRICE_PLN",
        "MIN_FLIP_SCORE", "MIN_MARGIN_PCT",
        "MAX_FRAUD_RISK", "MARKETPLACE_FEE_PCT",
        "MARKET_PRICES_PATH", "LOG_LEVEL",
        "AI_REQUEST_DELAY_SECONDS",
    ]
    for key in env_keys:
        monkeypatch.delenv(key, raising=False)


class TestSettingsDefaults:
    def test_creates_without_env_file(self) -> None:
        settings = Settings(_env_file=None)
        assert settings is not None

    def test_default_openai_base_url(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.openai_base_url == "https://api.openai.com/v1"

    def test_default_openai_model(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.openai_model == "gpt-4o-mini"

    def test_default_database_path(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.database_path == "data/flip_finder.db"

    def test_default_delays(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.request_min_delay == 2.0
        assert settings.request_max_delay == 6.0

    def test_default_concurrency(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.max_concurrent_requests == 2

    def test_default_search_queries(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.search_queries == ["iPhone 13", "iPhone 14", "iPhone 15", "iPhone 16"]

    def test_default_scoring(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.min_flip_score == 70.0
        assert settings.min_margin_pct == 15.0
        assert settings.max_fraud_risk == 0.3
        assert settings.marketplace_fee_pct == 0.0

    def test_secrets_are_none_by_default(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.openai_api_key is None
        assert settings.telegram_bot_token is None
        assert settings.telegram_chat_id is None

    def test_default_log_level(self) -> None:
        settings = Settings(_env_file=None)
        assert settings.log_level == "INFO"

    def test_default_ai_request_delay(self) -> None:
        assert Settings(_env_file=None).ai_request_delay_seconds == 4.0


class TestSearchQueriesParsing:
    def test_comma_separated_string(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SEARCH_QUERIES", "iPhone 13,iPhone 14 Pro,iPhone 15 Pro Max")
        settings = Settings(_env_file=None)
        assert settings.search_queries == ["iPhone 13", "iPhone 14 Pro", "iPhone 15 Pro Max"]

    def test_whitespace_stripped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SEARCH_QUERIES", " iPhone 13 , iPhone 14 , iPhone 15 ")
        settings = Settings(_env_file=None)
        assert settings.search_queries == ["iPhone 13", "iPhone 14", "iPhone 15"]

    def test_empty_elements_removed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SEARCH_QUERIES", "iPhone 13,,iPhone 14,,")
        settings = Settings(_env_file=None)
        assert settings.search_queries == ["iPhone 13", "iPhone 14"]

    def test_single_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SEARCH_QUERIES", "iPhone 15 Pro")
        settings = Settings(_env_file=None)
        assert settings.search_queries == ["iPhone 15 Pro"]

    def test_list_input_passthrough(self) -> None:
        settings = Settings(_env_file=None, search_queries=["iPhone 16", "iPhone 16 Pro"])
        assert settings.search_queries == ["iPhone 16", "iPhone 16 Pro"]


def test_blank_optional_settings_become_none() -> None:
    settings = Settings(_env_file=None, openai_api_key="", http_proxy="")
    assert settings.openai_api_key is None
    assert settings.http_proxy is None


class TestSettingsValidation:
    def test_negative_min_delay(self) -> None:
        with pytest.raises(ValidationError, match="request_min_delay"):
            Settings(_env_file=None, request_min_delay=-1.0)

    def test_max_delay_less_than_min_delay(self) -> None:
        with pytest.raises(ValidationError, match="request_max_delay"):
            Settings(_env_file=None, request_min_delay=5.0, request_max_delay=2.0)

    def test_zero_concurrent_requests(self) -> None:
        with pytest.raises(ValidationError, match="max_concurrent_requests"):
            Settings(_env_file=None, max_concurrent_requests=0)

    def test_zero_search_max_pages(self) -> None:
        with pytest.raises(ValidationError, match="search_max_pages"):
            Settings(_env_file=None, search_max_pages=0)

    def test_max_buy_price_below_min_sanity(self) -> None:
        with pytest.raises(ValidationError, match="max_buy_price_pln"):
            Settings(_env_file=None, max_buy_price_pln=50, min_sanity_price_pln=100)

    def test_equal_buy_and_sanity_prices(self) -> None:
        with pytest.raises(ValidationError, match="max_buy_price_pln"):
            Settings(_env_file=None, max_buy_price_pln=100, min_sanity_price_pln=100)

    def test_flip_score_out_of_range(self) -> None:
        with pytest.raises(ValidationError, match="min_flip_score"):
            Settings(_env_file=None, min_flip_score=150.0)

    def test_negative_min_margin(self) -> None:
        with pytest.raises(ValidationError, match="min_margin_pct"):
            Settings(_env_file=None, min_margin_pct=-5.0)

    def test_fraud_risk_above_one(self) -> None:
        with pytest.raises(ValidationError, match="max_fraud_risk"):
            Settings(_env_file=None, max_fraud_risk=1.5)

    def test_negative_fraud_risk(self) -> None:
        with pytest.raises(ValidationError, match="max_fraud_risk"):
            Settings(_env_file=None, max_fraud_risk=-0.1)

    def test_negative_fee_pct(self) -> None:
        with pytest.raises(ValidationError, match="marketplace_fee_pct"):
            Settings(_env_file=None, marketplace_fee_pct=-1.0)

    def test_negative_ai_request_delay(self) -> None:
        with pytest.raises(ValidationError, match="ai_request_delay_seconds"):
            Settings(_env_file=None, ai_request_delay_seconds=-1)
