"""Inspect aggregated device-related OLX embedded params from one browser page."""
from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
import json

from app.config import Settings
from app.scrapers.browser_fetcher import BrowserFetcher
from app.scrapers.olx import IPHONE_CATEGORY_URL, OLXScraper


async def main() -> None:
    settings = Settings()
    fetcher = BrowserFetcher(headless=False, browser_channel="chrome")
    html = await fetcher.fetch_html(IPHONE_CATEGORY_URL)
    scraper = OLXScraper(settings)
    state = scraper._extract_prerendered_state(html)
    ads = state["listing"]["listing"]["ads"]

    counts: Counter[str] = Counter()
    values: dict[str, Counter[str]] = defaultdict(Counter)
    examples = []
    for ad in ads:
        params = scraper._parse_params(ad)
        for key, value in params.items():
            if isinstance(value, (str, int, float, bool)):
                counts[key] += 1
                values[key][str(value)] += 1
        listing = scraper._listing_from_ad(ad)
        if listing and scraper._matches_query(listing, "iPhone 15 Pro"):
            examples.append({
                "external_id": listing.external_id,
                "title": listing.title,
                "price": f"{listing.price} {listing.currency}",
                "params": params,
            })
    print(json.dumps({
        "browser": fetcher.last_metadata.browser if fetcher.last_metadata else None,
        "final_url": fetcher.last_metadata.final_url if fetcher.last_metadata else None,
        "title": fetcher.last_metadata.title if fetcher.last_metadata else None,
        "status": fetcher.last_metadata.status if fetcher.last_metadata else None,
        "listings": len(ads),
        "param_key_counts": dict(sorted(counts.items())),
        "param_key_values": {key: dict(counter.most_common(20)) for key, counter in sorted(values.items())},
        "iphone_15_pro_examples": examples[:10],
    }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
