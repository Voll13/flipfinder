from __future__ import annotations

import asyncio
import logging
import random
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.config import Settings
from app.exceptions import ScraperBlockedError, ScraperError
from app.models import Listing

logger = logging.getLogger(__name__)

USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (X11; Linux x86_64; rv:133.0) Gecko/20100101 Firefox/133.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Safari/605.1.15",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1",
)

BLOCK_MARKERS: tuple[str, ...] = (
    "captcha",
    "cf-chl",
    "turnstile",
    "verify you are human",
    "checking your browser",
    "access denied",
    "challenge-platform",
)


class BaseScraper(ABC):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_requests)

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                proxy=self._settings.http_proxy,
                timeout=self._settings.request_timeout,
                follow_redirects=True,
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> BaseScraper:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    def _get_random_user_agent(self) -> str:
        return random.choice(USER_AGENTS)

    def _base_headers(self) -> dict[str, str]:
        return {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }

    async def _wait_before_request(self) -> None:
        delay = random.uniform(
            self._settings.request_min_delay,
            self._settings.request_max_delay,
        )
        logger.debug("Waiting %.2f seconds before request", delay)
        await asyncio.sleep(delay)

    async def _wait_before_retry(self, attempt: int) -> None:
        backoff = 2 ** attempt
        logger.debug("Waiting %d seconds before retry attempt %d", backoff, attempt)
        await asyncio.sleep(backoff)

    def _is_html_response(self, response: httpx.Response) -> bool:
        content_type = response.headers.get("content-type", "")
        return "text/html" in content_type or "application/xhtml+xml" in content_type

    def _check_for_block(self, response: httpx.Response) -> None:
        if response.status_code in (403, 429):
            raise ScraperBlockedError(
                f"Blocked with HTTP {response.status_code} for URL: {response.url}"
            )

        if self._is_html_response(response):
            body_lower = response.text.lower()
            for marker in BLOCK_MARKERS:
                if marker in body_lower:
                    raise ScraperBlockedError(
                        f"Anti-bot challenge detected (marker: '{marker}') for URL: {response.url}"
                    )

    async def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> httpx.Response:
        max_attempts = 3
        last_exc: Exception | None = None

        caller_headers = kwargs.pop("headers", None)
        headers = self._base_headers()
        headers["User-Agent"] = self._get_random_user_agent()
        if caller_headers:
            headers.update(caller_headers)
        kwargs["headers"] = headers

        for attempt in range(max_attempts):
            await self._wait_before_request()

            async with self._semaphore:
                client = await self._get_client()
                logger.debug(
                    "Attempt %d/%d: %s %s",
                    attempt + 1,
                    max_attempts,
                    method,
                    url,
                )

                try:
                    response = await client.request(method, url, **kwargs)

                    self._check_for_block(response)

                    if 200 <= response.status_code < 300:
                        return response

                    if 400 <= response.status_code < 500:
                        raise ScraperError(
                            f"HTTP {response.status_code} for URL: {url}"
                        )

                    if 500 <= response.status_code < 600:
                        logger.warning(
                            "Temporary server error HTTP %d for URL: %s (attempt %d/%d)",
                            response.status_code,
                            url,
                            attempt + 1,
                            max_attempts,
                        )
                        if attempt < max_attempts - 1:
                            await self._wait_before_retry(attempt)
                            continue
                        raise ScraperError(
                            f"HTTP {response.status_code} for URL: {url} after {max_attempts} attempts"
                        )

                    raise ScraperError(
                        f"Unexpected HTTP {response.status_code} for URL: {url}"
                    )

                except (
                    httpx.TimeoutException,
                    httpx.ConnectError,
                    httpx.NetworkError,
                ) as exc:
                    logger.warning(
                        "Network error for URL: %s (attempt %d/%d): %s",
                        url,
                        attempt + 1,
                        max_attempts,
                        exc,
                    )
                    last_exc = exc
                    if attempt < max_attempts - 1:
                        await self._wait_before_retry(attempt)
                        continue

        assert last_exc is not None
        raise ScraperError(
            f"Request failed for URL: {url} after {max_attempts} attempts"
        ) from last_exc

    @abstractmethod
    async def search(
        self,
        query: str,
        state: str | None = None,
        price_from: int | None = None,
        price_to: int | None = None,
        district_id: str | None = None,
        max_pages: int = 1,
    ) -> list[Listing]:
        ...

    @abstractmethod
    async def fetch_details(self, listing: Listing) -> Listing:
        ...
