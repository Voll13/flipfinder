"""Application workflow joining search, analysis, persistence and alerts."""
from __future__ import annotations

import json
import logging
import asyncio
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.config import Settings
from app.exceptions import AIAnalysisError, ScraperBlockedError, ScraperError
from app.models import AIAnalysis, DeviceInfo, FlipEvaluation, Listing
from app.scoring import SCORING_VERSION, FlipScorer
from app.scrapers.base import BaseScraper
from app.services.ai_analyzer import AIAnalyzer
from app.services.candidate_filters import matches_location, matches_model
from app.services.market_data import MarketDataProvider
from app.services.market_benchmark import MarketBenchmarkBuilder
from app.services.resale_estimator import ResaleEstimator
from app.services.telegram_notifier import TelegramNotifier
from app.storage.database import Database

logger = logging.getLogger(__name__)


@dataclass
class PipelineStats:
    found: int = 0
    unique: int = 0
    market_raw: int = 0
    market_unique: int = 0
    query_candidates: int = 0
    processed_candidates: int = 0
    market_available: int = 0
    market_unavailable: int = 0
    market_eligible_total: int = 0
    ranked_for_ai: int = 0
    stale_evaluations: int = 0
    rescored: int = 0
    rescored_candidates: int = 0
    rescored_alerts: int = 0
    persistent_market_rows: int = 0
    persistent_recent_rows: int = 0
    known: int = 0
    known_analyzed_unchanged: int = 0
    known_unanalyzed: int = 0
    deferred_market_eligible: int = 0
    deferred_analyzed: int = 0
    new: int = 0
    analyzed: int = 0
    candidates: int = 0
    alerts_sent: int = 0
    price_drops: int = 0
    errors: int = 0


class FlipPipeline:
    def __init__(
        self, scraper: BaseScraper, analyzer: AIAnalyzer, scorer: FlipScorer,
        database: Database, notifier: TelegramNotifier, market: MarketDataProvider,
        settings: Settings, benchmark_builder: MarketBenchmarkBuilder | None = None,
        resale_estimator: ResaleEstimator | None = None,
    ) -> None:
        self.scraper = scraper
        self.analyzer = analyzer
        self.scorer = scorer
        self.database = database
        self.notifier = notifier
        self.market = market
        self.settings = settings
        self.benchmark_builder = benchmark_builder
        self.resale_estimator = resale_estimator or ResaleEstimator()
        self.stats = PipelineStats()
        self._ai_requests_started = 0

    def _preliminary_market(self, listing: Listing, universe: list[Listing]):
        dynamic = self.benchmark_builder.lookup_for_listing(listing, universe) if self.benchmark_builder else None
        static = self.market.lookup_for_listing(listing)
        selected = dynamic or static
        if dynamic:
            self.stats.market_available += 1
            logger.info("Market benchmark: dynamic, sample=%d min=%d median=%s avg=%d max=%d", dynamic.sample_size, dynamic.min_price, dynamic.median_price, dynamic.avg_price, dynamic.max_price)
        elif static:
            self.stats.market_available += 1
            logger.info("Market benchmark: static")
        else:
            self.stats.market_unavailable += 1
            logger.info("Skipping AI: no deterministic market benchmark")
        return dynamic, static, selected

    def _final_market(self, dynamic, static, analysis: AIAnalysis):
        if dynamic is not None:
            return dynamic, "dynamic_market"
        refined = self.market.lookup_for_device(analysis.device_info)
        if refined is not None:
            return refined, "static_market"
        if static is not None:
            return static, "static_market"
        return None, None

    def _evaluate(self, listing: Listing, analysis: AIAnalysis, dynamic, static):
        market, source = self._final_market(dynamic, static, analysis)
        estimate = self.resale_estimator.estimate(listing, analysis, market, source or "static_market")
        return self.scorer.evaluate(listing, analysis, market, estimate), estimate, market

    def _log_evaluation(self, listing: Listing, analysis: AIAnalysis, evaluation: FlipEvaluation, market) -> None:
        rejected: list[str] = []
        if evaluation.margin_pct < self.settings.min_margin_pct:
            rejected.append("margin_below_threshold")
        if evaluation.flip_score < self.settings.min_flip_score:
            rejected.append("score_below_threshold")
        if analysis.fraud_risk > self.settings.max_fraud_risk:
            rejected.append("fraud_risk")
        if any(reason.startswith("Hard stop:") for reason in evaluation.reasons):
            rejected.append("hard_stop")
        logger.info(
            "Evaluation: external_id=%s asking=%d market_median=%s deterministic_resale=%s profit=%d margin=%.1f%% score=%.1f fraud_risk=%.2f candidate=%s%s",
            listing.external_id, listing.price, getattr(market, "median_price", None), evaluation.resale_price_used,
            evaluation.estimated_profit, evaluation.margin_pct, evaluation.flip_score, analysis.fraud_risk,
            evaluation.is_flip_candidate,
            f" reject_reason={','.join(rejected)}" if rejected else "",
        )

    @staticmethod
    def _needs_details(listing: Listing) -> bool:
        return not listing.description or not listing.description.strip()

    @staticmethod
    def _listing_from_row(row: dict[str, Any]) -> Listing:
        published = row.get("published_at")
        return Listing(
            source=row["source"], external_id=str(row["external_id"]), url=row["url"],
            title=row["title"], price=row["price"], currency=row["currency"],
            location=row.get("location"), seller_type=row.get("seller_type"),
            published_at=datetime.fromisoformat(published) if published else None,
            description=row.get("description"),
            photo_urls=json.loads(row["photo_urls"] or "[]"), id=row.get("id"),
            attributes=json.loads(row.get("attributes_json") or "{}"),
        )

    @staticmethod
    def _stored_models(row: dict[str, Any]) -> tuple[AIAnalysis, FlipEvaluation]:
        return (
            AIAnalysis.model_validate(json.loads(row["analysis_json"])),
            FlipEvaluation.model_validate(json.loads(row["evaluation_json"])),
        )

    async def _retry_unsent_alerts(self) -> None:
        for row in await self.database.get_unsent_flips(limit=100):
            try:
                listing = self._listing_from_row(row)
                analysis, evaluation = self._stored_models(row)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                logger.warning("Skipping unsent listing %s with invalid stored data: %s", row.get("id"), exc)
                self.stats.errors += 1
                continue
            if evaluation.resale_source not in {"dynamic_market", "static_market"}:
                logger.info("Skipping unsent listing %s: no deterministic market benchmark", row["id"])
                continue
            try:
                await self.notifier.send_alert(listing, evaluation, analysis)
                if not getattr(self.notifier, "is_dry_run", False):
                    await self.database.mark_sent(row["id"])
                    self.stats.alerts_sent += 1
            except Exception as exc:
                logger.error("Telegram retry failed for %s:%s: %s", listing.source, listing.external_id, exc)
                self.stats.errors += 1

    async def _send(self, listing: Listing, evaluation: FlipEvaluation, analysis: AIAnalysis, listing_id: int, previous_price: int | None = None) -> None:
        try:
            await self.notifier.send_alert(listing, evaluation, analysis, previous_price)
            # is_sent records the initial alert only; price-drop alerts are events.
            if previous_price is None and not getattr(self.notifier, "is_dry_run", False):
                await self.database.mark_sent(listing_id)
            if not getattr(self.notifier, "is_dry_run", False):
                self.stats.alerts_sent += 1
        except Exception as exc:
            logger.error("Telegram alert failed for %s:%s: %s", listing.source, listing.external_id, exc)
            self.stats.errors += 1

    async def _rescore_stored(self, listing: Listing, row: dict[str, Any], listing_id: int, universe: list[Listing], *, stale: bool = False, previous_price: int | None = None) -> FlipEvaluation | None:
        try:
            analysis, old_evaluation = self._stored_models(row)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.warning("Cannot re-score %s:%s: invalid stored analysis: %s", listing.source, listing.external_id, exc)
            self.stats.errors += 1
            return None
        dynamic, static, preliminary = self._preliminary_market(listing, universe)
        if preliminary is None:
            return None
        evaluation, estimate, market = self._evaluate(listing, analysis, dynamic, static)
        self._log_evaluation(listing, analysis, evaluation, market)
        await self.database.update_listing_analysis(listing_id, analysis.device_info, analysis, evaluation)
        if stale:
            self.stats.rescored += 1
            logger.info(
                "Rescore: external_id=%s scoring_version=%d→%d old_score=%.1f new_score=%.1f old_candidate=%s new_candidate=%s",
                listing.external_id, old_evaluation.scoring_version, SCORING_VERSION,
                old_evaluation.flip_score, evaluation.flip_score,
                old_evaluation.is_flip_candidate, evaluation.is_flip_candidate,
            )
        if evaluation.is_flip_candidate:
            self.stats.candidates += 1
            if stale:
                self.stats.rescored_candidates += 1
            if estimate is None:
                logger.info("Candidate suppressed: no deterministic market benchmark")
            elif previous_price is not None:
                await self._send(listing, evaluation, analysis, listing_id, previous_price=previous_price)
            elif stale and not old_evaluation.is_flip_candidate and not row.get("is_sent"):
                self.stats.rescored_alerts += 1
                await self._send(listing, evaluation, analysis, listing_id)
            return evaluation
        return None

    async def _process_unanalyzed(self, listing: Listing, universe: list[Listing], listing_id: int, deferred: bool = False, preliminary_market=None) -> FlipEvaluation | None:
        if not self.settings.min_sanity_price_pln <= listing.price <= self.settings.max_buy_price_pln:
            logger.warning("Skipping out-of-range listing %s:%s", listing.source, listing.external_id)
            return None
        dynamic, static, preliminary = preliminary_market or self._preliminary_market(listing, universe)
        if preliminary is None:
            return None
        if deferred:
            self.stats.deferred_market_eligible += 1
        if self._needs_details(listing):
            try:
                listing = await self.scraper.fetch_details(listing)
                listing_id, _ = await self.database.upsert_listing(listing)
            except ScraperBlockedError:
                raise
            except ScraperError as exc:
                logger.warning("Details failed for %s:%s: %s", listing.source, listing.external_id, exc)
                self.stats.errors += 1
                if self._needs_details(listing):
                    return None
        try:
            if self._ai_requests_started and self.settings.ai_request_delay_seconds:
                await asyncio.sleep(self.settings.ai_request_delay_seconds)
            self.stats.processed_candidates += 1
            self._ai_requests_started += 1
            analysis = await self.analyzer.analyze(listing, preliminary)
        except (AIAnalysisError, Exception) as exc:
            logger.error("AI analysis failed for %s:%s: %s", listing.source, listing.external_id, exc)
            self.stats.errors += 1
            return None
        self.stats.analyzed += 1
        if deferred:
            self.stats.deferred_analyzed += 1
        evaluation, estimate, market = self._evaluate(listing, analysis, dynamic, static)
        self._log_evaluation(listing, analysis, evaluation, market)
        await self.database.update_listing_analysis(listing_id, analysis.device_info, analysis, evaluation)
        if evaluation.is_flip_candidate:
            self.stats.candidates += 1
            if estimate is None:
                logger.info("Candidate suppressed: no deterministic market benchmark")
            else:
                await self._send(listing, evaluation, analysis, listing_id)
            return evaluation
        return None

    async def _process_new(self, listing: Listing, universe: list[Listing]) -> FlipEvaluation | None:
        listing_id, _ = await self.database.upsert_listing(listing)
        return await self._process_unanalyzed(listing, universe, listing_id)

    @staticmethod
    def _deduplicate(listings: list[Listing]) -> list[Listing]:
        result: list[Listing] = []
        seen: set[tuple[str, str]] = set()
        for listing in listings:
            key = (listing.source, listing.external_id)
            if key not in seen:
                seen.add(key)
                result.append(listing)
        return result

    @staticmethod
    def _matches_query(listing: Listing, query: str) -> bool:
        return " ".join(query.casefold().split()) in " ".join(listing.title.casefold().split())

    async def run(
        self, queries: list[str] | None = None, max_pages: int | None = None,
        limit: int | None = None, external_id: str | None = None,
    ) -> list[FlipEvaluation]:
        self.stats = PipelineStats()
        pages = self.settings.search_max_pages if max_pages is None else max_pages
        all_listings: list[Listing] = []
        for query in (self.settings.search_queries if queries is None else queries):
            try:
                found = await self.scraper.search(query=query, state=None, price_from=self.settings.min_sanity_price_pln, price_to=self.settings.max_buy_price_pln, district_id=None, max_pages=pages)
                logger.info("Search query %r found %d listings", query, len(found))
                all_listings.extend(found)
            except ScraperBlockedError as exc:
                logger.error("OLX scraping blocked; stopping search: %s", exc)
                self.stats.errors += 1
                break
            except ScraperError as exc:
                logger.error("Search failed for %r: %s", query, exc)
                self.stats.errors += 1
        # Scraper search already applies query filters in legacy/httpx modes.
        return await self._run_listing_sets(all_listings, all_listings, limit, external_id)

    async def run_from_listings(self, listings: list[Listing], queries: list[str] | None = None, limit: int | None = None, external_id: str | None = None, benchmark_universe: list[Listing] | None = None, models: list[str] | None = None, cities: list[str] | None = None, voivodeships: list[str] | None = None) -> list[FlipEvaluation]:
        market_universe = self._deduplicate(listings)
        persistent_universe = self._deduplicate(benchmark_universe) if benchmark_universe is not None else market_universe
        selected_queries = self.settings.search_queries if queries is None else queries
        candidates = self._deduplicate([listing for listing in market_universe if (any(matches_model(listing, model) for model in models) if models else any(self._matches_query(listing, query) for query in selected_queries)) and matches_location(listing, cities, voivodeships)])
        return await self._run_listing_sets(market_universe, candidates, limit, external_id, persistent_universe)

    async def _run_listing_sets(self, market_listings: list[Listing], candidates: list[Listing], limit: int | None, external_id: str | None, benchmark_universe: list[Listing] | None = None) -> list[FlipEvaluation]:
        self.stats = PipelineStats(errors=self.stats.errors)
        self._ai_requests_started = 0
        await self._retry_unsent_alerts()
        self.stats.found = len(market_listings)
        market_universe = self._deduplicate(market_listings)
        persistent_universe = self._deduplicate(benchmark_universe) if benchmark_universe is not None else market_universe
        unique = self._deduplicate(candidates)
        self.stats.unique = len(market_universe)
        self.stats.market_raw = len(market_listings)
        self.stats.market_unique = len(market_universe)
        self.stats.query_candidates = len(unique)
        self.stats.persistent_market_rows = len(persistent_universe)
        self.stats.persistent_recent_rows = len(persistent_universe)
        logger.info("Market universe: current_raw=%d current_unique=%d persistent_recent=%d query_candidates=%d", len(market_listings), len(market_universe), len(persistent_universe), len(unique))
        if external_id is not None:
            unique = [listing for listing in unique if listing.external_id == external_id]
            logger.info("Processing selected external_id=%s: %d listings", external_id, len(unique))

        results: list[FlipEvaluation] = []
        details_blocked = False
        ranked: list[tuple[Listing, int | None, bool, tuple[object, object, object], float, int, int]] = []
        for listing in unique:
            existing = await self.database.get_listing_by_external_id(listing.source, listing.external_id)
            if existing is not None:
                self.stats.known += 1
                old_price = int(existing["price"])
                listing_id = await self.database.touch_listing(listing)
                if existing.get("analysis_json") is None:
                    self.stats.known_unanalyzed += 1
                    if self.settings.min_sanity_price_pln <= listing.price <= self.settings.max_buy_price_pln:
                        dynamic, static, preliminary = self._preliminary_market(listing, persistent_universe)
                        if preliminary is not None:
                            ranked.append(self._ranked_entry(listing, listing_id, True, dynamic, static, preliminary))
                else:
                    try:
                        _, saved_evaluation = self._stored_models(existing)
                    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                        logger.warning("Cannot inspect stored evaluation for %s:%s: %s", listing.source, listing.external_id, exc)
                        self.stats.errors += 1
                        continue
                    stale = saved_evaluation.scoring_version < SCORING_VERSION
                    price_changed = listing.price < old_price
                    if stale:
                        self.stats.stale_evaluations += 1
                    if price_changed:
                        self.stats.price_drops += 1
                    if stale or price_changed:
                        result = await self._rescore_stored(
                            listing, existing, listing_id, persistent_universe,
                            stale=stale, previous_price=old_price if price_changed else None,
                        )
                        if result:
                            results.append(result)
                    else:
                        self.stats.known_analyzed_unchanged += 1
                continue
            self.stats.new += 1
            if self.settings.min_sanity_price_pln <= listing.price <= self.settings.max_buy_price_pln:
                dynamic, static, preliminary = self._preliminary_market(listing, persistent_universe)
                if preliminary is not None:
                    # Preserve the existing limit behaviour: listings outside the
                    # selected ranked window are not inserted merely because they
                    # were examined for a free benchmark.
                    ranked.append(self._ranked_entry(listing, None, False, dynamic, static, preliminary))
                else:
                    await self.database.upsert_listing(listing)
            else:
                await self.database.upsert_listing(listing)

        self.stats.market_eligible_total = len(ranked)
        ranked.sort(key=lambda entry: (entry[4], entry[5], entry[6]), reverse=True)
        selected = ranked if limit is None else ranked[:limit]
        self.stats.ranked_for_ai = len(selected)
        for listing, listing_id, deferred, dynamic_static_preliminary, preliminary_margin, sample_size, _published in selected:
            dynamic, static, preliminary = dynamic_static_preliminary
            logger.info(
                "Pre-AI rank: external_id=%s asking=%d market_median=%s preliminary_margin=%.1f%% market_N=%d",
                listing.external_id, listing.price, preliminary.median_price, preliminary_margin, sample_size,
            )
            if details_blocked and self._needs_details(listing):
                logger.warning("Skipping %s:%s after OLX block", listing.source, listing.external_id)
                continue
            try:
                if listing_id is None:
                    listing_id, _ = await self.database.upsert_listing(listing)
                result = await self._process_unanalyzed(
                    listing, persistent_universe, listing_id, deferred=deferred,
                    preliminary_market=(dynamic, static, preliminary),
                )
            except ScraperBlockedError as exc:
                logger.error("OLX details blocked; no further detail requests this run: %s", exc)
                self.stats.errors += 1
                details_blocked = True
                continue
            if result:
                results.append(result)
        logger.info("Pipeline completed: %s", self.stats)
        return results

    @staticmethod
    def _ranked_entry(listing: Listing, listing_id: int | None, deferred: bool, dynamic, static, preliminary):
        """Build a stable, pre-LLM opportunity rank without changing final scoring."""
        anchor = preliminary.median_price if preliminary.median_price is not None else preliminary.avg_price
        margin = ((anchor - listing.price) / listing.price * 100) if listing.price > 0 else float("-inf")
        published = int(listing.published_at.timestamp()) if listing.published_at is not None else 0
        return listing, listing_id, deferred, (dynamic, static, preliminary), margin, preliminary.sample_size, published
