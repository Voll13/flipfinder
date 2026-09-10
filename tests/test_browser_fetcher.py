from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.exceptions import ScraperBlockedError
from app.main import BrowserOLXScraper
from app.scrapers.browser_fetcher import BrowserFetcher
from app.scrapers.olx import IPHONE_CATEGORY_URL, OLXScraper


class FakeFactory:
    def __init__(self, status=200, title="OLX", body="normal page", html="<html></html>", document_html=None):
        response = SimpleNamespace(status=status)
        if document_html is not None:
            response.text = AsyncMock(return_value=document_html)
        self.page = SimpleNamespace(
            url="https://www.olx.pl/final",
            goto=AsyncMock(return_value=response),
            title=AsyncMock(return_value=title),
            locator=lambda selector: SimpleNamespace(inner_text=AsyncMock(return_value=body)),
            content=AsyncMock(return_value=html),
            close=AsyncMock(),
        )
        self.context = SimpleNamespace(new_page=AsyncMock(return_value=self.page), close=AsyncMock())
        self.browser = SimpleNamespace(new_context=AsyncMock(return_value=self.context), close=AsyncMock())
        self.playwright = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=self.browser)))

    def __call__(self):
        return self

    async def __aenter__(self):
        return self.playwright

    async def __aexit__(self, *args):
        return None


@pytest.mark.asyncio
async def test_fetch_html_uses_one_normal_page_and_closes_resources():
    factory = FakeFactory(html="<html>captured</html>")
    fetcher = BrowserFetcher(headless=False, playwright_factory=factory)
    assert await fetcher.fetch_html("https://example.test") == "<html>captured</html>"
    assert factory.playwright.chromium.launch.await_args.kwargs == {"headless": False}
    assert factory.page.goto.await_args.kwargs["wait_until"] == "domcontentloaded"
    assert fetcher.last_metadata and fetcher.last_metadata.status == 200
    factory.page.close.assert_awaited_once()
    factory.context.close.assert_awaited_once()
    factory.browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_document_response_with_embedded_state_is_preferred_without_extra_navigation():
    factory = FakeFactory(html="<html>rendered</html>", document_html='<script id="olx-init-config">window.__PRERENDERED_STATE__</script>')
    fetcher = BrowserFetcher(playwright_factory=factory)
    html = await fetcher.fetch_html("https://example.test")
    assert "__PRERENDERED_STATE__" in html
    assert fetcher.last_metadata and fetcher.last_metadata.html_source == "document_response"
    factory.page.goto.assert_awaited_once()
    factory.page.content.assert_not_awaited()


@pytest.mark.asyncio
async def test_rendered_dom_is_used_when_document_response_has_no_embedded_state():
    factory = FakeFactory(html="<html>rendered state</html>", document_html="<html>plain document</html>")
    fetcher = BrowserFetcher(playwright_factory=factory)
    assert await fetcher.fetch_html("https://example.test") == "<html>rendered state</html>"
    assert fetcher.last_metadata and fetcher.last_metadata.html_source == "rendered_dom"
    factory.page.goto.assert_awaited_once()
    factory.page.content.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetcher_can_use_installed_chrome_channel():
    factory = FakeFactory()
    await BrowserFetcher(playwright_factory=factory, browser_channel="chrome").fetch_html("https://example.test")
    assert factory.playwright.chromium.launch.await_args.kwargs["channel"] == "chrome"


@pytest.mark.asyncio
async def test_challenge_stops_and_still_closes_resources():
    factory = FakeFactory(title="Access Denied")
    fetcher = BrowserFetcher(playwright_factory=factory)
    with pytest.raises(ScraperBlockedError):
        await fetcher.fetch_html("https://example.test")
    factory.browser.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_many_pages_are_sequential_and_stop_after_block_on_page_two():
    factory = FakeFactory()
    factory.page.goto.side_effect = [SimpleNamespace(status=200), SimpleNamespace(status=403)]
    fetcher = BrowserFetcher(playwright_factory=factory)
    with pytest.raises(ScraperBlockedError):
        await fetcher.fetch_many_html(["https://x/1", "https://x/2", "https://x/3"])
    assert factory.page.goto.await_count == 2
    assert [call.args[0] for call in factory.page.goto.await_args_list] == ["https://x/1", "https://x/2"]


@pytest.mark.asyncio
async def test_browser_adapter_passes_fetcher_html_to_existing_parser():
    fixture = ("tests/fixtures/olx_search_minimal.html")
    html = open(fixture, encoding="utf-8").read()
    parser = OLXScraper(Settings(_env_file=None))
    fetcher = SimpleNamespace(fetch_many_html=AsyncMock(return_value=[html]), last_metadata=SimpleNamespace(browser="Chromium", final_url=IPHONE_CATEGORY_URL, title="OLX", status=200))
    adapter = BrowserOLXScraper(parser, fetcher)
    listings = await adapter.search("iphone", max_pages=1)
    assert [item.external_id for item in listings] == ["9001"]
    fetcher.fetch_many_html.assert_awaited_once()


@pytest.mark.asyncio
async def test_browser_adapter_builds_page_urls_and_deduplicates_market_pages():
    first = OLXScraper(Settings(_env_file=None)).parse_search_html(open("tests/fixtures/olx_search_minimal.html", encoding="utf-8").read())
    second = [first[0].model_copy(update={"external_id": "9002"}), first[0]]
    parser = SimpleNamespace(_settings=Settings(_env_file=None), _build_page_url=lambda page: f"https://x?page={page}", parse_search_html=lambda html: first if html == "one" else second)
    fetcher = SimpleNamespace(fetch_many_html=AsyncMock(return_value=["one", "two"]))
    listings = await BrowserOLXScraper(parser, fetcher, market_pages=2).collect_market_universe()
    assert [item.external_id for item in listings] == ["9001", "9002"]
    assert fetcher.fetch_many_html.await_args.args[0] == ["https://x?page=1", "https://x?page=2"]


@pytest.mark.asyncio
async def test_browser_adapter_logs_embedded_source_and_structured_coverage(caplog):
    caplog.set_level("INFO")
    html = open("tests/fixtures/olx_search_minimal.html", encoding="utf-8").read()
    parser = OLXScraper(Settings(_env_file=None))
    fetcher = SimpleNamespace(fetch_many_html=AsyncMock(return_value=[html]))
    await BrowserOLXScraper(parser, fetcher).collect_market_universe()
    assert "parser_source=embedded" in caplog.text
    assert "html_source=unknown" in caplog.text
    assert "structured_model=" in caplog.text and "structured_storage=" in caplog.text and "structured_state=" in caplog.text
