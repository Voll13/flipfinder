"""One-page, ordinary-browser acquisition for OLX validation."""
from __future__ import annotations

from dataclasses import dataclass
import asyncio
import logging
import random
from typing import Any, Callable

from playwright.async_api import async_playwright

from app.exceptions import ScraperBlockedError, ScraperError
from app.scrapers.base import BLOCK_MARKERS

_BROWSER_BLOCK_MARKERS = (*BLOCK_MARKERS, "access denied", "unusual traffic")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrowserPageMetadata:
    final_url: str
    title: str
    status: int | None
    browser: str = "Chromium"
    html_source: str = "rendered_dom"


class BrowserFetcher:
    """Fetch one document with stock Playwright Chromium and no evasion logic."""

    def __init__(self, headless: bool = False, timeout_ms: int = 30_000, playwright_factory: Callable[[], Any] | None = None, browser_channel: str | None = None) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._playwright_factory = playwright_factory or async_playwright
        self.browser_channel = browser_channel
        self.last_metadata: BrowserPageMetadata | None = None
        self.page_metadata: list[BrowserPageMetadata] = []

    @staticmethod
    def _is_blocked(title: str, body: str) -> bool:
        text = f"{title}\n{body}".casefold()
        return any(marker in text for marker in _BROWSER_BLOCK_MARKERS)

    @staticmethod
    def _has_embedded_state(html: str | None) -> bool:
        return bool(html and ("olx-init-config" in html or "__PRERENDERED_STATE__" in html))

    @staticmethod
    async def _document_response_html(response: Any) -> str | None:
        """Read the body already obtained by Playwright's main navigation."""
        text = getattr(response, "text", None)
        if not callable(text):
            return None
        try:
            value = await text()
        except Exception as exc:
            logger.debug("Could not read browser document response body: %s", exc)
            return None
        return value if isinstance(value, str) else None

    async def fetch_html(self, url: str) -> str:
        return (await self.fetch_many_html([url]))[0]

    async def fetch_many_html(self, urls: list[str], min_delay: float = 0, max_delay: float = 0) -> list[str]:
        if not urls:
            return []
        if min_delay < 0 or max_delay < min_delay:
            raise ValueError("invalid browser navigation delay range")
        self.page_metadata = []
        async with self._playwright_factory() as playwright:
            launch_options = {"headless": self.headless}
            if self.browser_channel:
                launch_options["channel"] = self.browser_channel
            browser = await playwright.chromium.launch(**launch_options)
            context = None
            page = None
            try:
                context = await browser.new_context()
                page = await context.new_page()
                pages: list[str] = []
                for index, url in enumerate(urls):
                    if index:
                        await asyncio.sleep(random.uniform(min_delay, max_delay))
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                    title = await page.title()
                    body = await page.locator("body").inner_text(timeout=self.timeout_ms)
                    status = response.status if response is not None else None
                    browser_name = "Google Chrome" if self.browser_channel == "chrome" else "Chromium"
                    document_html = await self._document_response_html(response) if response is not None else None
                    if self._has_embedded_state(document_html):
                        html, html_source = document_html, "document_response"
                    else:
                        html, html_source = await page.content(), "rendered_dom"
                    self.last_metadata = BrowserPageMetadata(page.url, title, status, browser_name, html_source)
                    self.page_metadata.append(self.last_metadata)
                    if status in {403, 429} or self._is_blocked(title, body):
                        raise ScraperBlockedError(f"Browser navigation was blocked for URL: {page.url}")
                    if status is not None and status >= 400:
                        raise ScraperError(f"Browser navigation returned HTTP {status} for URL: {page.url}")
                    pages.append(html)
                return pages
            finally:
                if page is not None:
                    await page.close()
                if context is not None:
                    await context.close()
                await browser.close()
