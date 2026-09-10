"""Command-line entry point for the iPhone flip finder."""
from __future__ import annotations

import argparse
import asyncio
import logging
from contextlib import AsyncExitStack
from pathlib import Path

from app.config import Settings
from app.exceptions import ConfigurationError, ScraperError
from app.pipeline import FlipPipeline
from app.scoring import FlipScorer
from app.scrapers.browser_fetcher import BrowserFetcher
from app.scrapers.olx import OLXScraper
from app.services.ai_analyzer import AIAnalyzer
from app.services.market_data import MarketDataProvider
from app.services.market_benchmark import MarketBenchmarkBuilder
from app.services.monitor import MonitorRunner
from app.services.resale_estimator import ResaleEstimator
from app.services.telegram_notifier import TelegramNotifier
from app.storage.database import Database
from app.version import VERSION

logger = logging.getLogger(__name__)


class DryRunNotifier:
    is_dry_run = True

    async def send_alert(self, listing, evaluation, analysis, previous_price=None) -> None:
        logger.info("Dry-run alert for %s:%s (score %.1f)", listing.source, listing.external_id, evaluation.flip_score)


class OfflineOLXScraper:
    """Search adapter for an OLX page saved locally in a normal browser."""

    def __init__(self, parser: OLXScraper, html_file: str) -> None:
        self._parser = parser
        self._listings = parser.parse_search_html(Path(html_file).read_text(encoding="utf-8"))

    async def search(self, query: str, state=None, price_from=None, price_to=None, district_id=None, max_pages=1):
        if district_id is not None:
            raise NotImplementedError("Offline OLX adapter does not support district filtering")
        if max_pages < 1:
            raise ValueError("max_pages must be >= 1")
        return self._parser.filter_search_results(self._listings, query, state, price_from, price_to)

    async def fetch_details(self, listing):
        raise ScraperError("Offline OLX input has no detail-page snapshot for this listing")


class BrowserOLXScraper:
    """One-page browser acquisition feeding the normal OLX HTML parser."""

    def __init__(self, parser: OLXScraper, fetcher: BrowserFetcher, market_pages: int = 1) -> None:
        self._parser = parser
        self._fetcher = fetcher
        self._market_pages = market_pages

    async def collect_market_universe(self):
        urls = [self._parser._build_page_url(page) for page in range(1, self._market_pages + 1)]
        html_pages = await self._fetcher.fetch_many_html(urls, self._parser._settings.request_min_delay, self._parser._settings.request_max_delay)
        listings = []
        for page_number, html in enumerate(html_pages, start=1):
            parsed = self._parser.parse_search_html(html)
            model_count = sum(bool(item.attributes.get("phonemodel")) for item in parsed)
            storage_count = sum(bool(item.attributes.get("builtinmemory_phones")) for item in parsed)
            state_count = sum(bool(item.attributes.get("state")) for item in parsed)
            logger.info(
                "OLX page %d: html_source=%s parser_source=%s listings=%d structured_model=%d/%d structured_storage=%d/%d structured_state=%d/%d",
                page_number, self._page_html_source(page_number), getattr(self._parser, "last_search_parse_source", "unknown"), len(parsed),
                model_count, len(parsed), storage_count, len(parsed), state_count, len(parsed),
            )
            listings.extend(parsed)
        deduped = []
        seen = set()
        for listing in listings:
            key = (listing.source, listing.external_id)
            if key not in seen:
                seen.add(key)
                deduped.append(listing)
        logger.info("Browser market pages=%d loaded=%d raw=%d unique=%d", self._market_pages, len(html_pages), len(listings), len(deduped))
        return deduped

    def _page_html_source(self, page_number: int) -> str:
        metadata = getattr(self._fetcher, "page_metadata", [])
        if page_number <= len(metadata):
            return getattr(metadata[page_number - 1], "html_source", "unknown")
        return "unknown"

    async def search(self, query: str, state=None, price_from=None, price_to=None, district_id=None, max_pages=1):
        if district_id is not None:
            raise NotImplementedError("Browser OLX adapter does not support district filtering")
        parsed = await self.collect_market_universe()
        return self._parser.filter_search_results(parsed, query, state, price_from, price_to)

    async def fetch_details(self, listing):
        raise ScraperError("Browser validation mode has no detail-page fetch")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find promising iPhone resale listings")
    parser.add_argument("--version", action="version", version=f"FlipFinder {VERSION}")
    parser.add_argument("--dry-run", action="store_true", help="perform analysis but log alerts")
    parser.add_argument("--pages", type=int, help="search pages per query")
    parser.add_argument("--query", action="append", help="query to search; repeat for several queries")
    parser.add_argument("--limit", type=int, help="maximum unique listings to process")
    parser.add_argument("--external-id", help="process one listing while retaining all search results as comparables")
    parser.add_argument("--market-pages", type=int, help="browser market pages (1-5; monitor default 5)")
    parser.add_argument("--telegram-test", action="store_true", help="send one Telegram connectivity test without OLX, AI, or database access")
    parser.add_argument("--market-only", action="store_true", help="persist browser market listings without AI, scoring, or Telegram")
    parser.add_argument("--monitor", action="store_true", help="run sequential browser monitoring cycles")
    parser.add_argument("--interval", type=int, help="monitor interval in minutes (5-1440)")
    parser.add_argument("--max-cycles", type=int, help="developer bound for monitor cycles")
    parser.add_argument("--model", action="append", help="exact structured iPhone model; repeatable")
    parser.add_argument("--city", action="append", help="candidate city filter; repeatable")
    parser.add_argument("--voivodeship", action="append", help="candidate voivodeship filter; repeatable")
    input_mode = parser.add_mutually_exclusive_group()
    input_mode.add_argument("--html-file", help="locally saved OLX search HTML; performs no OLX requests")
    input_mode.add_argument("--browser", action="store_true", help="fetch OLX page 1 in ordinary Playwright Chromium")
    parser.add_argument("--database", help="SQLite database path override")
    return parser.parse_args(argv)


async def _run_once(args: argparse.Namespace, settings: Settings):
    if args.pages is not None and args.pages < 1:
        raise ValueError("--pages must be >= 1")
    if args.limit is not None and args.limit < 1:
        raise ValueError("--limit must be >= 1")
    if not 1 <= args.market_pages <= 5:
        raise ValueError("--market-pages must be between 1 and 5")
    if args.market_only and not args.browser:
        raise ValueError("--market-only requires --browser")

    # Constructing these before search gives configuration failures immediately.
    async with AsyncExitStack() as stack:
        database = await stack.enter_async_context(Database(args.database or settings.database_path))
        parser_scraper = OLXScraper(settings)
        if args.html_file:
            scraper = OfflineOLXScraper(parser_scraper, args.html_file)
        elif args.browser:
            scraper = BrowserOLXScraper(parser_scraper, BrowserFetcher(headless=False, browser_channel="chrome"), args.market_pages)
        else:
            scraper = await stack.enter_async_context(parser_scraper)
        current_market_universe = None
        persistent_market_universe = None
        if args.browser:
            current_market_universe = await scraper.collect_market_universe()
            await database.upsert_market_listings(current_market_universe)
            persistent_market_universe = await database.get_market_universe(settings.market_lookback_hours)
            logger.info("Persistent market universe: total=%d recent_%dh=%d", await database.market_listing_count(), settings.market_lookback_hours, len(persistent_market_universe))
            if args.market_only:
                builder = MarketBenchmarkBuilder()
                queries = args.query or settings.search_queries
                candidates = [listing for listing in current_market_universe if any(" ".join(query.casefold().split()) in " ".join(listing.title.casefold().split()) for query in queries)]
                for listing in candidates:
                    key = builder._key(listing)
                    logger.info("Market coverage: %s -> comparable=%d", key, builder.comparable_count_for_listing(listing, persistent_market_universe))
                return None
        analyzer = await stack.enter_async_context(AIAnalyzer(settings))
        notifier = DryRunNotifier() if args.dry_run else await stack.enter_async_context(TelegramNotifier(settings))
        market = MarketDataProvider(settings.market_prices_path)
        await market.load()
        pipeline = FlipPipeline(scraper, analyzer, FlipScorer(settings), database, notifier, market, settings, MarketBenchmarkBuilder(), ResaleEstimator())
        if args.browser:
            await pipeline.run_from_listings(current_market_universe or [], queries=args.query, limit=args.limit, external_id=args.external_id, benchmark_universe=persistent_market_universe, models=args.model, cities=args.city, voivodeships=args.voivodeship)
        else:
            await pipeline.run(queries=args.query, max_pages=args.pages, limit=args.limit, external_id=args.external_id)
        return pipeline.stats


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    settings = Settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO), format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    if args.telegram_test:
        async with TelegramNotifier(settings) as notifier:
            result = await notifier.send_test_message()
        message_id = getattr(result, "message_id", None)
        logger.info("Telegram test completed%s", f" (message_id={message_id})" if message_id is not None else "")
        return
    if args.monitor:
        args.browser = True
    args.market_pages = args.market_pages or (5 if args.monitor else 1)
    if args.interval is not None and not 5 <= args.interval <= 1440:
        raise ValueError("--interval must be between 5 and 1440")
    if args.max_cycles is not None and args.max_cycles < 1:
        raise ValueError("--max-cycles must be >= 1")
    if args.monitor:
        interval = (args.interval or settings.monitor_interval_minutes) * 60
        await MonitorRunner(lambda: _run_once(args, settings), interval, args.max_cycles).run()
    else:
        await _run_once(args, settings)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except ConfigurationError as exc:
        logger.error("Configuration error: %s", exc)
        raise SystemExit(2) from exc
    except KeyboardInterrupt:
        logger.info("Monitoring stopped")
