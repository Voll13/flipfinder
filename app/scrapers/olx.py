"""OLX scraper using embedded pre-rendered page state."""
from __future__ import annotations

import logging, re
from datetime import datetime
from typing import Any
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from bs4 import BeautifulSoup
from app.exceptions import ScraperError
from app.marketplaces.olx.embedded_state import extract_prerendered_state
from app.models import Listing
from app.scrapers.base import BaseScraper
from app.services.market_data import MarketDataProvider

logger = logging.getLogger(__name__)
IPHONE_CATEGORY_URL = "https://www.olx.pl/elektronika/telefony/smartfony-telefony-komorkowe/iphone/"

class OLXScraper(BaseScraper):
    def __init__(self, settings) -> None:
        super().__init__(settings)
        self.last_search_parse_source: str | None = None

    def _build_page_url(self, page: int) -> str:
        if page <= 1: return IPHONE_CATEGORY_URL
        p = urlsplit(IPHONE_CATEGORY_URL)
        return urlunsplit((p.scheme, p.netloc, p.path, urlencode({"page": page}), ""))

    def _extract_prerendered_state(self, html: str) -> dict[str, Any]:
        return extract_prerendered_state(html)

    @staticmethod
    def _text(value: object) -> str | None:
        return " ".join(value.split()) or None if isinstance(value, str) else None
    def _price(self, ad: dict[str, Any]) -> tuple[int, str] | None:
        regular = ad.get("price", {}).get("regularPrice", {}) if isinstance(ad.get("price"), dict) else {}
        if not isinstance(regular, dict):
            return None
        value = regular.get("value"); currency = self._text(regular.get("currencyCode")) or "PLN"
        if isinstance(value, bool): return None
        try: number = int(float(value))
        except (TypeError, ValueError): return None
        try: integral = float(value).is_integer()
        except (TypeError, ValueError): integral = False
        return (number, currency) if number >= 0 and integral else None
    def _location(self, ad: dict[str, Any]) -> str | None:
        loc = ad.get("location")
        if not isinstance(loc, dict): return None
        values = list(dict.fromkeys(x for x in (self._text(loc.get(k)) for k in ("cityName","districtName","regionName")) if x))
        return ", ".join(values) if values else self._text(loc.get("pathName"))
    def _location_attributes(self, ad: dict[str, Any]) -> dict[str, str]:
        loc = ad.get("location")
        if not isinstance(loc, dict): return {}
        return {f"location_{target}": value for target,key in (("city","cityName"),("region","regionName"),("district","districtName")) if (value := self._text(loc.get(key)))}
    @staticmethod
    def _datetime(value: object) -> datetime | None:
        try: return datetime.fromisoformat(value) if isinstance(value, str) else None
        except ValueError: logger.warning("Ignoring malformed OLX createdTime"); return None
    def _clean_description(self, value: object) -> str | None:
        if not isinstance(value, str) or not value.strip(): return None
        soup = BeautifulSoup(value, "html.parser")
        for tag in soup.find_all(["br", "p", "li"]): tag.insert_after("\n")
        return "\n".join(x for x in (" ".join(line.split()) for line in soup.get_text("\n").splitlines()) if x) or None
    def _parse_photo_urls(self, ad: dict[str, Any]) -> list[str]:
        result: list[str] = []
        for url in ad.get("photos", []) if isinstance(ad.get("photos"), list) else []:
            if isinstance(url, str) and url.strip() and url not in result: result.append(url)
        return result
    def _parse_params(self, ad: dict[str, Any]) -> dict[str, str]:
        if not isinstance(ad.get("params"), list): return {}
        result: dict[str, str] = {}
        for item in ad["params"]:
            if not isinstance(item, dict) or not isinstance(item.get("key"), str): continue
            key = self._text(item["key"])
            value = self._text(item.get("normalizedValue", item.get("value")))
            if key and value: result[key] = value
        return result
    @staticmethod
    def _title_attributes(title: str) -> dict[str, str]:
        """Infer only unambiguous model/storage hints for DOM fallback listings."""
        model, storage = MarketDataProvider("").extract_device_hint(title)
        attributes: dict[str, str] = {}
        if model:
            attributes["phonemodel"] = model.casefold().replace(" ", "-")
        if storage is not None:
            attributes["builtinmemory_phones"] = f"{storage}gb"
        return attributes
    def _listing_from_ad(self, ad: dict[str, Any]) -> Listing | None:
        if not isinstance(ad, dict): return None
        ident, title = ad.get("id"), self._text(ad.get("title")); url = self._text(ad.get("url")) or self._text(ad.get("urlPath")); price = self._price(ad)
        if ident is None or not title or not url or not price: logger.warning("Skipping malformed OLX ad"); return None
        business = ad.get("isBusiness")
        return Listing(source="olx", external_id=str(ident), url=urljoin("https://www.olx.pl/", url), title=title, price=price[0], currency=price[1], location=self._location(ad), seller_type="business" if business is True else "private" if business is False else None, published_at=self._datetime(ad.get("createdTime")), description=self._clean_description(ad.get("description")), photo_urls=self._parse_photo_urls(ad), attributes=self._parse_params(ad) | self._location_attributes(ad))
    def _parse_search_html(self, html: str) -> list[Listing]:
        try:
            ads = self._extract_prerendered_state(html).get("listing", {}).get("listing", {}).get("ads")
            if not isinstance(ads, list): raise ScraperError("OLX search ads are missing")
            self.last_search_parse_source = "embedded"
            return [x for ad in ads if isinstance(ad, dict) and (x := self._listing_from_ad(ad))]
        except ScraperError:
            self.last_search_parse_source = "dom_fallback"
            logger.warning("OLX embedded search state missing; using DOM fallback")
        soup = BeautifulSoup(html, "html.parser"); out=[]
        for card in soup.select('[data-testid="l-card"][data-cy="l-card"]'):
            link=card.select_one('[data-testid="card-title-link"]'); price=card.select_one('[data-testid="ad-price"]'); title=self._text(link.get_text()) if link else None; number=re.search(r"\d[\d\s]*", price.get_text() if price else "")
            if card.get("id") and link and link.get("href") and title and number: out.append(Listing(source="olx",external_id=str(card["id"]),url=urljoin("https://www.olx.pl/",link["href"]),title=title,price=int(number.group().replace(" ","")),location=self._text((card.select_one('[data-testid="location-date"]') or "").get_text() if card.select_one('[data-testid="location-date"]') else None),attributes=self._title_attributes(title)))
        return out
    def parse_search_html(self, html: str) -> list[Listing]:
        """Parse a previously captured OLX search page without making a request."""
        return self._parse_search_html(html)
    def _matches_query(self, listing: Listing, query: str) -> bool: return " ".join(query.casefold().split()) in " ".join(listing.title.casefold().split())
    def filter_search_results(self, listings: list[Listing], query: str, state: str | None = None, price_from: int | None = None, price_to: int | None = None) -> list[Listing]:
        if state is not None and state.casefold() not in {"private","business"}: raise ValueError("state must be 'private', 'business', or None")
        return [x for x in listings if self._matches_query(x,query) and (price_from is None or x.price>=price_from) and (price_to is None or x.price<=price_to) and (state is None or x.seller_type==state.casefold())]
    async def search(self, query: str, state: str | None = None, price_from: int | None = None, price_to: int | None = None, district_id: str | None = None, max_pages: int = 1) -> list[Listing]:
        if district_id is not None: raise NotImplementedError("OLX district_id filtering is not implemented because the public filter parameter contract has not been confirmed.")
        if state is not None and state.casefold() not in {"private","business"}: raise ValueError("state must be 'private', 'business', or None")
        if max_pages < 1: raise ValueError("max_pages must be >= 1")
        out=[]; seen=set()
        for page in range(1,max_pages+1):
            parsed=self._parse_search_html((await self._request("GET",self._build_page_url(page))).text)
            if not parsed: break
            kept=self.filter_search_results(parsed,query,state,price_from,price_to)
            logger.info("OLX page %d: parsed=%d after_filters=%d",page,len(parsed),len(kept))
            for x in kept:
                if x.external_id not in seen: seen.add(x.external_id); out.append(x)
        return out
    def _parse_detail_html(self, html: str, listing: Listing) -> Listing:
        try: parsed=self._listing_from_ad(self._extract_prerendered_state(html).get("ad",{}).get("ad",{}))
        except (ScraperError, AttributeError): parsed=None
        if not parsed: logger.warning("OLX embedded detail state missing; returning existing listing"); return listing
        if parsed.external_id != listing.external_id: logger.warning("OLX detail ID mismatch"); return parsed.model_copy(update={"external_id":listing.external_id})
        return parsed
    async def fetch_details(self, listing: Listing) -> Listing: return self._parse_detail_html((await self._request("GET",listing.url)).text,listing)
