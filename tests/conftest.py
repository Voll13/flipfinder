from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.scrapers.base import BaseScraper


@pytest.fixture(autouse=True)
def _no_scraper_waits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(BaseScraper, "_wait_before_request", AsyncMock())
    monkeypatch.setattr(BaseScraper, "_wait_before_retry", AsyncMock())


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock()
    client.is_closed = False
    client.aclose = AsyncMock()
    return client
