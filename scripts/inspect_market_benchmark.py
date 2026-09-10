"""Build dynamic benchmark diagnostics from one ordinary-browser OLX page."""
from __future__ import annotations

import asyncio
import json

from app.config import Settings
from app.scrapers.browser_fetcher import BrowserFetcher
from app.scrapers.olx import IPHONE_CATEGORY_URL, OLXScraper
from app.services.market_benchmark import MarketBenchmarkBuilder


async def main() -> None:
    fetcher = BrowserFetcher(headless=False, browser_channel="chrome")
    html = await fetcher.fetch_html(IPHONE_CATEGORY_URL)
    parser = OLXScraper(Settings())
    listings = parser.parse_search_html(html)
    builder = MarketBenchmarkBuilder()
    builder.build(listings)
    diagnostics = list(builder.diagnostics)
    target = next(item for item in listings if item.external_id == "1095620361")
    benchmark = builder.lookup_for_listing(target, listings)
    target_diagnostic = next((item for item in builder.diagnostics if (item.model, item.storage_gb, item.condition, item.currency) == ("iPhone 15 Pro", 128, "good", "PLN")), None)
    print(json.dumps({
        "browser": fetcher.last_metadata.browser if fetcher.last_metadata else None,
        "status": fetcher.last_metadata.status if fetcher.last_metadata else None,
        "listings": len(listings),
        "iphone_15_pro": [item.__dict__ for item in diagnostics if item.model == "iPhone 15 Pro"],
        "target": {
            "external_id": target.external_id,
            "asking_price": target.price,
            "benchmark": benchmark.model_dump(mode="json") if benchmark else None,
            "diagnostic": target_diagnostic.__dict__ if target_diagnostic else None,
            "vs_median_pct": round((target.price - target_diagnostic.median_price) / target_diagnostic.median_price * 100, 1) if target_diagnostic and target_diagnostic.median_price else None,
        },
    }, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())
