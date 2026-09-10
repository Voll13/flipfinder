from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.config import Settings
from app.exceptions import ScraperBlockedError, ScraperError
from app.models import Listing
from app.scrapers.base import USER_AGENTS, BaseScraper


class DummyScraper(BaseScraper):
    async def search(self, query: str, **kwargs) -> list[Listing]:
        return []

    async def fetch_details(self, listing: Listing) -> Listing:
        return listing


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        request_min_delay=0.0,
        request_max_delay=0.0,
        max_concurrent_requests=2,
        request_timeout=5.0,
    )


@pytest.fixture
def scraper(settings: Settings) -> DummyScraper:
    return DummyScraper(settings)


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock(spec=httpx.AsyncClient)
    client.is_closed = False
    client.aclose = AsyncMock()
    client.request = AsyncMock()
    return client


def _make_response(
    status: int,
    method: str = "GET",
    url: str = "https://example.com",
    headers: dict | None = None,
    text: str = "",
) -> httpx.Response:
    return httpx.Response(
        status,
        request=httpx.Request(method, url),
        headers=headers or {},
        text=text,
    )


# ── Client lifecycle ─────────────────────────────────


class TestClientLifecycle:
    @pytest.mark.asyncio
    async def test_client_lazy_creation(self, scraper: DummyScraper) -> None:
        assert scraper._client is None
        client = await scraper._get_client()
        assert client is not None
        assert scraper._client is client
        await scraper.close()

    @pytest.mark.asyncio
    async def test_close_works(self, scraper: DummyScraper) -> None:
        await scraper._get_client()
        await scraper.close()
        assert scraper._client is None

    @pytest.mark.asyncio
    async def test_double_close_safe(self, scraper: DummyScraper) -> None:
        await scraper._get_client()
        await scraper.close()
        await scraper.close()
        assert scraper._client is None

    @pytest.mark.asyncio
    async def test_async_context_manager(self, settings: Settings) -> None:
        async with DummyScraper(settings) as s:
            await s._get_client()
            assert s._client is not None
        assert s._client is None


# ── User-Agent ───────────────────────────────────────


class TestUserAgent:
    def test_random_ua_from_list(self, scraper: DummyScraper) -> None:
        ua = scraper._get_random_user_agent()
        assert ua in USER_AGENTS

    @pytest.mark.asyncio
    async def test_request_includes_ua(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(200)

        await scraper._request("GET", "https://example.com")

        call_kwargs = mock_client.request.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["User-Agent"] in USER_AGENTS

    @pytest.mark.asyncio
    async def test_different_ua_per_request(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(200)

        uas_seen: set[str] = set()
        for _ in range(10):
            await scraper._request("GET", "https://example.com")
            call_kwargs = mock_client.request.call_args
            headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
            uas_seen.add(headers["User-Agent"])

        assert all(ua in USER_AGENTS for ua in uas_seen)


# ── Headers ──────────────────────────────────────────


class TestHeaders:
    @pytest.mark.asyncio
    async def test_base_headers_present(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(200)

        await scraper._request("GET", "https://example.com")

        call_kwargs = mock_client.request.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert "Accept" in headers
        assert "Accept-Language" in headers
        assert "Accept-Encoding" in headers

    @pytest.mark.asyncio
    async def test_caller_headers_added(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(200)

        await scraper._request(
            "GET", "https://example.com", headers={"X-Custom": "value"}
        )

        call_kwargs = mock_client.request.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["X-Custom"] == "value"

    @pytest.mark.asyncio
    async def test_caller_ua_override(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(200)

        custom_ua = "CustomBot/1.0"
        await scraper._request(
            "GET", "https://example.com", headers={"User-Agent": custom_ua}
        )

        call_kwargs = mock_client.request.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers")
        assert headers["User-Agent"] == custom_ua


# ── 2xx ──────────────────────────────────────────────


class TestSuccessResponse:
    @pytest.mark.asyncio
    async def test_200_returned(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(200)

        response = await scraper._request("GET", "https://example.com")
        assert response.status_code == 200


# ── 403 ──────────────────────────────────────────────


class TestHTTP403:
    @pytest.mark.asyncio
    async def test_403_raises_blocked(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(403)

        with pytest.raises(ScraperBlockedError):
            await scraper._request("GET", "https://example.com")

    @pytest.mark.asyncio
    async def test_403_no_retry(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(403)

        with pytest.raises(ScraperBlockedError):
            await scraper._request("GET", "https://example.com")

        assert mock_client.request.call_count == 1


# ── 429 ──────────────────────────────────────────────


class TestHTTP429:
    @pytest.mark.asyncio
    async def test_429_raises_blocked(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(429)

        with pytest.raises(ScraperBlockedError):
            await scraper._request("GET", "https://example.com")

    @pytest.mark.asyncio
    async def test_429_no_retry(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(429)

        with pytest.raises(ScraperBlockedError):
            await scraper._request("GET", "https://example.com")

        assert mock_client.request.call_count == 1


# ── Challenge page ───────────────────────────────────


class TestChallengePage:
    @pytest.mark.asyncio
    async def test_captcha_page(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body>Please complete the CAPTCHA to continue</body></html>",
        )

        with pytest.raises(ScraperBlockedError):
            await scraper._request("GET", "https://example.com")

        assert mock_client.request.call_count == 1

    @pytest.mark.asyncio
    async def test_turnstile_page(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body><div class='cf-turnstile'>Verify you are human</div></body></html>",
        )

        with pytest.raises(ScraperBlockedError):
            await scraper._request("GET", "https://example.com")

        assert mock_client.request.call_count == 1

    @pytest.mark.asyncio
    async def test_false_positive_cloudflare(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(
            200,
            headers={"content-type": "text/html"},
            text="<html><body><p>Normal page</p><script src='cloudflare-analytics.js'></script></body></html>",
        )

        response = await scraper._request("GET", "https://example.com")
        assert response.status_code == 200


# ── 4xx ──────────────────────────────────────────────


class TestHTTP4xx:
    @pytest.mark.asyncio
    async def test_404_raises_error(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(404)

        with pytest.raises(ScraperError):
            await scraper._request("GET", "https://example.com")

    @pytest.mark.asyncio
    async def test_400_raises_error(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(400)

        with pytest.raises(ScraperError):
            await scraper._request("GET", "https://example.com")

    @pytest.mark.asyncio
    async def test_404_no_retry(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(404)

        with pytest.raises(ScraperError):
            await scraper._request("GET", "https://example.com")

        assert mock_client.request.call_count == 1


# ── 5xx ──────────────────────────────────────────────


class TestHTTP5xx:
    @pytest.mark.asyncio
    async def test_500_retry(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(500)

        with pytest.raises(ScraperError):
            await scraper._request("GET", "https://example.com")

        assert mock_client.request.call_count == 3

    @pytest.mark.asyncio
    async def test_503_retry(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(503)

        with pytest.raises(ScraperError):
            await scraper._request("GET", "https://example.com")

        assert mock_client.request.call_count == 3

    @pytest.mark.asyncio
    async def test_500_500_200_success(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.side_effect = [
            _make_response(500),
            _make_response(500),
            _make_response(200),
        ]

        response = await scraper._request("GET", "https://example.com")
        assert response.status_code == 200
        assert mock_client.request.call_count == 3

    @pytest.mark.asyncio
    async def test_500_500_500_fails(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(500)

        with pytest.raises(ScraperError):
            await scraper._request("GET", "https://example.com")

        assert mock_client.request.call_count == 3

    @pytest.mark.asyncio
    async def test_exactly_3_attempts(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(500)

        with pytest.raises(ScraperError):
            await scraper._request("GET", "https://example.com")

        assert mock_client.request.call_count == 3

    @pytest.mark.asyncio
    async def test_500_500_200_call_counts(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.side_effect = [
            _make_response(500),
            _make_response(500),
            _make_response(200),
        ]

        await scraper._request("GET", "https://example.com")

        assert mock_client.request.call_count == 3
        assert scraper._wait_before_request.call_count == 3
        assert scraper._wait_before_retry.call_count == 2

    @pytest.mark.asyncio
    async def test_500_500_500_call_counts(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(500)

        with pytest.raises(ScraperError):
            await scraper._request("GET", "https://example.com")

        assert mock_client.request.call_count == 3
        assert scraper._wait_before_request.call_count == 3
        assert scraper._wait_before_retry.call_count == 2


# ── Network ──────────────────────────────────────────


class TestNetworkErrors:
    @pytest.mark.asyncio
    async def test_timeout_retry(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.side_effect = [
            httpx.TimeoutException("timeout"),
            httpx.TimeoutException("timeout"),
            _make_response(200),
        ]

        response = await scraper._request("GET", "https://example.com")
        assert response.status_code == 200
        assert mock_client.request.call_count == 3

    @pytest.mark.asyncio
    async def test_connect_error_retry(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.side_effect = [
            httpx.ConnectError("connection failed"),
            httpx.ConnectError("connection failed"),
            _make_response(200),
        ]

        response = await scraper._request("GET", "https://example.com")
        assert response.status_code == 200
        assert mock_client.request.call_count == 3

    @pytest.mark.asyncio
    async def test_network_error_error_success(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.side_effect = [
            httpx.NetworkError("network error"),
            httpx.TimeoutException("timeout"),
            _make_response(200),
        ]

        response = await scraper._request("GET", "https://example.com")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_three_failures_raises(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.side_effect = httpx.TimeoutException("timeout")

        with pytest.raises(ScraperError):
            await scraper._request("GET", "https://example.com")

    @pytest.mark.asyncio
    async def test_exception_chained(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        original_exc = httpx.TimeoutException("timeout")
        mock_client.request.side_effect = original_exc

        with pytest.raises(ScraperError) as exc_info:
            await scraper._request("GET", "https://example.com")

        assert exc_info.value.__cause__ is original_exc

    @pytest.mark.asyncio
    async def test_network_failures_call_counts(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.side_effect = httpx.TimeoutException("timeout")

        with pytest.raises(ScraperError):
            await scraper._request("GET", "https://example.com")

        assert mock_client.request.call_count == 3
        assert scraper._wait_before_request.call_count == 3
        assert scraper._wait_before_retry.call_count == 2


# ── Delay ────────────────────────────────────────────


class TestDelay:
    @pytest.mark.asyncio
    async def test_wait_before_request_called_once(
        self, scraper: DummyScraper, mock_client: MagicMock
    ) -> None:
        scraper._client = mock_client
        mock_client.request.return_value = _make_response(200)

        await scraper._request("GET", "https://example.com")
        assert scraper._wait_before_request.call_count == 1


# ── Semaphore ────────────────────────────────────────


class TestSemaphore:
    def test_semaphore_exists(self, scraper: DummyScraper, settings: Settings) -> None:
        assert hasattr(scraper, "_semaphore")
        assert scraper._semaphore._value == settings.max_concurrent_requests
