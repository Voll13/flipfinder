from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from app.config import Settings
from app.exceptions import AIAnalysisError, ScraperBlockedError, ScraperError
from app.models import AIAnalysis, DeviceInfo, FlipEvaluation, Listing, MarketPrice
from app.pipeline import FlipPipeline
from app.scoring import SCORING_VERSION, FlipScorer
from app.services.resale_estimator import ResaleEstimate
from app.services.market_benchmark import MarketBenchmarkBuilder
from app.storage.database import Database


def listing(external_id: str = "one", price: int = 2000, description: str | None = "complete text") -> Listing:
    return Listing(source="olx", external_id=external_id, url=f"https://olx/{external_id}", title="iPhone 14 128 GB", price=price, description=description)


def analysis(resale: int = 3000) -> AIAnalysis:
    return AIAnalysis(device_info=DeviceInfo(model="iPhone 14", storage_gb=128, condition="excellent"), estimated_resale_price=resale, resale_confidence=.9, fraud_risk=.05, summary="ok")


class Scraper:
    def __init__(self, responses: dict[str, list[Listing] | Exception]) -> None:
        self.responses = responses
        self.search = AsyncMock(side_effect=self._search)
        self.fetch_details = AsyncMock(side_effect=self._details)
        self.detail_error: Exception | None = None

    async def _search(self, query: str, **kwargs):
        value = self.responses[query]
        if isinstance(value, Exception):
            raise value
        return value

    async def _details(self, item: Listing) -> Listing:
        if self.detail_error:
            raise self.detail_error
        return item.model_copy(update={"description": "enriched text"})


class Analyzer:
    def __init__(self, result: AIAnalysis | Exception) -> None:
        self.result = result
        self.analyze = AsyncMock(side_effect=self._analyze)

    async def _analyze(self, item, market):
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Market:
    def __init__(self) -> None:
        self.preliminary = MarketPrice(model="iPhone 14", storage_gb=128, condition="good", min_price=2500, avg_price=2900, max_price=3200)
        self.refined = MarketPrice(model="iPhone 14", storage_gb=128, condition="excellent", min_price=2800, avg_price=3100, max_price=3400)
        self.listing_calls = []
        self.device_calls = []

    def lookup_for_listing(self, item):
        self.listing_calls.append(item)
        return self.preliminary

    def lookup_for_device(self, device):
        self.device_calls.append(device)
        return self.refined


class Benchmark:
    def __init__(self, market):
        self.market = market
        self.calls = []

    def lookup_for_listing(self, item, universe):
        self.calls.append((item, universe))
        return self.market


class SelectiveBenchmark:
    def __init__(self, markets):
        self.markets = markets
        self.calls = []

    def lookup_for_listing(self, item, universe):
        self.calls.append((item, universe))
        return self.markets.get(item.external_id)


class SpyScorer:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def evaluate(self, item, analyzed, market, resale_estimate=None):
        self.calls.append((item, analyzed, market, resale_estimate))
        return self.result


class TrackingEstimator:
    def __init__(self):
        self.calls = []

    def estimate(self, item, analyzed, market, source):
        self.calls.append((item, analyzed, market, source))
        if market is None:
            return None
        return ResaleEstimate(2500, .55, source, 2500, [], market.sample_size, market.min_price, market.median_price, market.avg_price, market.max_price)


class Notifier:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.send_alert = AsyncMock(side_effect=self._send)

    async def _send(self, *args):
        if self.failure:
            raise self.failure


class DryRunNotifier(Notifier):
    is_dry_run = True


def settings(**extra) -> Settings:
    values = {"search_queries": ["base"], "min_flip_score": 0, "min_margin_pct": 1, "ai_request_delay_seconds": 0}
    values.update(extra)
    return Settings(_env_file=None, **values)


@pytest_asyncio.fixture
async def database(tmp_path):
    async with Database(str(tmp_path / "pipeline.db")) as value:
        yield value


def pipeline(database, scraper, analyzer, notifier, market, configured=None, benchmark=None, scorer=None, resale_estimator=None):
    configured = configured or settings()
    return FlipPipeline(scraper, analyzer, scorer or FlipScorer(configured), database, notifier, market, configured, benchmark, resale_estimator)


@pytest.mark.asyncio
async def test_new_candidate_is_saved_scored_and_sent(database):
    item = listing()
    scraper, ai, notifier, market = Scraper({"base": [item]}), Analyzer(analysis()), Notifier(), Market()
    result = await pipeline(database, scraper, ai, notifier, market).run()

    assert len(result) == 1 and ai.analyze.await_count == 1 and notifier.send_alert.await_count == 1
    row = await database.get_listing_by_external_id("olx", "one")
    assert row["analysis_json"] and row["evaluation_json"] and row["is_sent"] == 1
    assert ai.analyze.await_args.args[1] is market.preliminary
    assert market.device_calls


@pytest.mark.asyncio
async def test_dynamic_market_is_preferred_for_ai_and_scorer_with_full_universe(database):
    dynamic = MarketPrice(model="iPhone 14", storage_gb=128, condition="good", min_price=2400, avg_price=2500, max_price=2600, sample_size=3)
    result = FlipScorer(settings()).evaluate(listing(), analysis())
    scorer = SpyScorer(result)
    items = [listing("one"), listing("two")]
    benchmark = Benchmark(dynamic)
    ai, market = Analyzer(analysis()), Market()
    await pipeline(database, Scraper({"base": items}), ai, Notifier(), market, benchmark=benchmark, scorer=scorer).run()
    assert ai.analyze.await_args.args[1] is dynamic and scorer.calls[0][2] is dynamic
    assert benchmark.calls[0][1] == items and benchmark.calls[0][0] is items[0]


@pytest.mark.asyncio
async def test_dynamic_market_calls_estimator_and_passes_result_to_scorer(database):
    dynamic = MarketPrice(model="iPhone 14", storage_gb=128, condition="good", min_price=2400, median_price=2500, avg_price=2500, max_price=2600, sample_size=3)
    estimator = TrackingEstimator()
    scorer = SpyScorer(FlipScorer(settings()).evaluate(listing(), analysis()))
    await pipeline(database, Scraper({"base": [listing()]}), Analyzer(analysis()), Notifier(), Market(), benchmark=Benchmark(dynamic), scorer=scorer, resale_estimator=estimator).run()
    assert estimator.calls[0][2] is dynamic and estimator.calls[0][3] == "dynamic_market"
    assert scorer.calls[0][3].source == "dynamic_market"


@pytest.mark.asyncio
async def test_no_market_candidate_is_saved_but_not_sent(database):
    class EmptyMarket:
        def lookup_for_listing(self, item): return None
        def lookup_for_device(self, device): return None
    notifier = Notifier()
    ai = Analyzer(analysis())
    scorer = SpyScorer(FlipScorer(settings()).evaluate(listing(), analysis()))
    worker = pipeline(database, Scraper({"base": [listing()]}), ai, notifier, EmptyMarket(), benchmark=Benchmark(None), scorer=scorer)
    await worker.run()
    row = await database.get_listing_by_external_id("olx", "one")
    assert row["analysis_json"] is None and row["evaluation_json"] is None
    assert ai.analyze.await_count == 0 and scorer.calls == [] and notifier.send_alert.await_count == 0
    assert worker.stats.market_unavailable == 1
    await pipeline(database, Scraper({"base": []}), Analyzer(analysis()), notifier, EmptyMarket(), benchmark=Benchmark(None)).run()
    assert notifier.send_alert.await_count == 0


@pytest.mark.asyncio
async def test_known_unanalyzed_is_deferred_until_market_becomes_available(database):
    item = listing()
    await database.upsert_listing(item)
    dynamic = MarketPrice(model="iPhone 14", storage_gb=128, condition="good", min_price=2400, median_price=2500, avg_price=2500, max_price=2600, sample_size=3)
    ai, notifier = Analyzer(analysis()), Notifier()
    worker = pipeline(database, Scraper({"base": [item]}), ai, notifier, Market(), benchmark=Benchmark(dynamic))
    await worker.run(limit=1)
    row = await database.get_listing_by_external_id("olx", "one")
    assert ai.analyze.await_count == 1 and row["analysis_json"] and row["evaluation_json"]
    assert worker.stats.known_unanalyzed == worker.stats.deferred_market_eligible == worker.stats.deferred_analyzed == 1
    assert notifier.send_alert.await_count == 1
    await worker.run(limit=1)
    assert ai.analyze.await_count == 1 and worker.stats.known_analyzed_unchanged == 1


@pytest.mark.asyncio
async def test_known_unanalyzed_without_market_skips_ai_but_price_drop_is_recorded(database):
    item = listing(price=2600)
    await database.upsert_listing(item)
    dropped = listing(price=2400)
    class EmptyMarket:
        def lookup_for_listing(self, item): return None
        def lookup_for_device(self, device): return None
    ai = Analyzer(analysis())
    worker = pipeline(database, Scraper({"base": [dropped]}), ai, Notifier(), EmptyMarket(), benchmark=Benchmark(None))
    await worker.run(limit=1)
    row = await database.get_listing_by_external_id("olx", "one")
    assert ai.analyze.await_count == 0 and row["analysis_json"] is None
    assert len(await database.get_price_history(row["id"])) == 2 and worker.stats.known_unanalyzed == 1


@pytest.mark.asyncio
async def test_limit_counts_deferred_and_new_first_analyses_together(database):
    deferred, fresh = listing("deferred"), listing("fresh")
    await database.upsert_listing(deferred)
    dynamic = MarketPrice(model="iPhone 14", storage_gb=128, condition="good", min_price=2400, median_price=2500, avg_price=2500, max_price=2600, sample_size=3)
    ai = Analyzer(analysis())
    worker = pipeline(database, Scraper({"base": [deferred, fresh]}), ai, Notifier(), Market(), benchmark=Benchmark(dynamic))
    await worker.run(limit=1)
    assert ai.analyze.await_count == 1 and ai.analyze.await_args.args[0].external_id == "deferred"
    assert (await database.get_listing_by_external_id("olx", "fresh")) is None


@pytest.mark.asyncio
async def test_limit_counts_market_eligible_candidates_not_leading_no_market(database):
    class EmptyMarket:
        def lookup_for_listing(self, item): return None
        def lookup_for_device(self, device): return None
    first, second = listing("first"), listing("second")
    dynamic = MarketPrice(model="iPhone 14", storage_gb=128, condition="good", min_price=2400, median_price=2500, avg_price=2500, max_price=2600, sample_size=3)
    ai = Analyzer(analysis())
    worker = pipeline(database, Scraper({"base": []}), ai, Notifier(), EmptyMarket(), benchmark=SelectiveBenchmark({"second": dynamic}))
    await worker.run_from_listings([first, second], queries=["iphone 14"], limit=1)
    assert ai.analyze.await_count == 1 and ai.analyze.await_args.args[0].external_id == "second"
    assert (worker.stats.market_unavailable, worker.stats.market_available, worker.stats.processed_candidates) == (1, 1, 1)


@pytest.mark.asyncio
async def test_static_market_makes_listing_eligible(database):
    ai = Analyzer(analysis())
    market = Market()
    worker = pipeline(database, Scraper({"base": [listing()]}), ai, Notifier(), market, benchmark=Benchmark(None))
    await worker.run()
    assert ai.analyze.await_count == 1 and worker.stats.market_available == 1


@pytest.mark.asyncio
async def test_run_from_listings_uses_full_market_universe_but_limits_query_candidates(database):
    candidate = listing("candidate")
    comparable = listing("comparable").model_copy(update={"title": "iPhone 14 128 GB"})
    nonmatching = listing("other").model_copy(update={"title": "iPhone 13 128 GB"})
    dynamic = MarketPrice(model="iPhone 14", storage_gb=128, condition="good", min_price=2400, avg_price=2500, max_price=2600, sample_size=3)
    benchmark = Benchmark(dynamic)
    ai = Analyzer(analysis())
    await pipeline(database, Scraper({"base": []}), ai, Notifier(), Market(), benchmark=benchmark).run_from_listings([candidate, comparable, nonmatching], queries=["iphone 14"], limit=1)
    assert ai.analyze.await_count == 1
    assert benchmark.calls[0][1] == [candidate, comparable, nonmatching]


@pytest.mark.asyncio
async def test_persistent_universe_enlarges_benchmark_but_current_snapshot_selects_candidates(database):
    def comparable(identifier, price):
        return listing(identifier, price).model_copy(update={"attributes": {"phonemodel": "iphone-14", "builtinmemory_phones": "128gb", "state": "used"}})
    current = comparable("current", 2000)
    old_comparables = [comparable("old-a", 2400), comparable("old-b", 2500), comparable("old-c", 2600)]
    class EmptyMarket:
        def lookup_for_listing(self, item): return None
        def lookup_for_device(self, device): return None
    ai = Analyzer(analysis())
    worker = pipeline(database, Scraper({"base": []}), ai, Notifier(), EmptyMarket(), benchmark=MarketBenchmarkBuilder())
    await worker.run_from_listings([current], queries=["iphone 14"], limit=1, benchmark_universe=[current, *old_comparables])
    assert ai.analyze.await_count == 1 and worker.stats.persistent_recent_rows == 4


@pytest.mark.asyncio
async def test_static_or_none_are_used_when_dynamic_is_unavailable(database):
    item, ai, market = listing(), Analyzer(analysis()), Market()
    await pipeline(database, Scraper({"base": [item]}), ai, Notifier(), market, benchmark=Benchmark(None)).run()
    assert ai.analyze.await_args.args[1] is market.preliminary

    class EmptyMarket:
        def lookup_for_listing(self, item): return None
        def lookup_for_device(self, device): return None
    empty_ai = Analyzer(analysis())
    await pipeline(database, Scraper({"base": [listing("empty")]}), empty_ai, Notifier(), EmptyMarket(), benchmark=Benchmark(None)).run()
    assert empty_ai.analyze.await_count == 0


@pytest.mark.asyncio
async def test_price_drop_rescoring_uses_dynamic_market(database):
    first, market = listing(price=2600), Market()
    await pipeline(database, Scraper({"base": [first]}), Analyzer(analysis()), Notifier(), market).run()
    dynamic = MarketPrice(model="iPhone 14", storage_gb=128, condition="good", min_price=2400, avg_price=2500, max_price=2600, sample_size=3)
    scorer = SpyScorer(FlipScorer(settings()).evaluate(listing(price=2400), analysis()))
    await pipeline(database, Scraper({"base": [listing(price=2400)]}), Analyzer(AIAnalysisError("must not run")), Notifier(), market, benchmark=Benchmark(dynamic), scorer=scorer).run()
    assert scorer.calls[0][2] is dynamic


@pytest.mark.asyncio
async def test_price_drop_uses_fresh_estimate_without_ai(database):
    first, market = listing(price=2600), Market()
    await pipeline(database, Scraper({"base": [first]}), Analyzer(analysis()), Notifier(), market).run()
    estimator = TrackingEstimator()
    await pipeline(database, Scraper({"base": [listing(price=2400)]}), Analyzer(AIAnalysisError("must not run")), Notifier(), market, resale_estimator=estimator).run()
    assert len(estimator.calls) == 1 and estimator.calls[0][0].price == 2400


@pytest.mark.asyncio
async def test_price_drop_without_market_skips_rescore_alert_and_ai(database):
    class EmptyMarket:
        def lookup_for_listing(self, item): return None
        def lookup_for_device(self, device): return None
    first, market = listing(price=2600), Market()
    await pipeline(database, Scraper({"base": [first]}), Analyzer(analysis()), Notifier(), market).run()
    ai, notifier = Analyzer(AIAnalysisError("must not run")), Notifier()
    worker = pipeline(database, Scraper({"base": [listing(price=2400)]}), ai, notifier, EmptyMarket(), benchmark=Benchmark(None))
    await worker.run()
    assert ai.analyze.await_count == 0 and notifier.send_alert.await_count == 0 and worker.stats.market_unavailable == 1


@pytest.mark.asyncio
async def test_dry_run_candidate_is_not_marked_sent(database):
    item = listing()
    scraper, ai, notifier, market = Scraper({"base": [item]}), Analyzer(analysis()), DryRunNotifier(), Market()
    await pipeline(database, scraper, ai, notifier, market).run()
    row = await database.get_listing_by_external_id("olx", "one")
    assert notifier.send_alert.await_count == 1 and row["is_sent"] == 0


@pytest.mark.asyncio
async def test_non_candidate_is_saved_without_alert_and_known_unchanged_is_skipped(database):
    item = listing()
    scraper, ai, notifier, market = Scraper({"base": [item]}), Analyzer(analysis(2000).model_copy(update={"fraud_risk": .9})), Notifier(), Market()
    worker = pipeline(database, scraper, ai, notifier, market)
    assert await worker.run() == []
    assert notifier.send_alert.await_count == 0
    await worker.run()
    assert ai.analyze.await_count == 1 and notifier.send_alert.await_count == 0


@pytest.mark.asyncio
async def test_duplicate_queries_are_processed_once_and_pass_pages(database):
    item = listing()
    scraper, ai, notifier, market = Scraper({"a": [item], "b": [item]}), Analyzer(analysis()), Notifier(), Market()
    await pipeline(database, scraper, ai, notifier, market).run(queries=["a", "b"], max_pages=2)

    assert ai.analyze.await_count == 1
    assert [call.kwargs["max_pages"] for call in scraper.search.await_args_list] == [2, 2]


@pytest.mark.asyncio
async def test_price_drop_rescores_stored_analysis_without_ai_and_alerts_once_per_new_price(database):
    first = listing(price=2600)
    initial_scraper, initial_ai, initial_notifier, market = Scraper({"base": [first]}), Analyzer(analysis()), Notifier(), Market()
    await pipeline(database, initial_scraper, initial_ai, initial_notifier, market).run()

    dropped = listing(price=2400)
    scraper, ai, notifier = Scraper({"base": [dropped]}), Analyzer(AIAnalysisError("must not run")), Notifier()
    worker = pipeline(database, scraper, ai, notifier, market)
    result = await worker.run()
    assert len(result) == 1 and ai.analyze.await_count == 0
    assert notifier.send_alert.await_args.args[3] == 2600
    await worker.run()
    assert notifier.send_alert.await_count == 1 and worker.stats.price_drops == 0


@pytest.mark.asyncio
async def test_price_drop_can_turn_a_saved_non_flip_into_candidate_without_ai(database):
    configured = settings(min_margin_pct=15)
    first = listing(price=2800)
    market = Market()
    await pipeline(database, Scraper({"base": [first]}), Analyzer(analysis(3000)), Notifier(), market, configured).run()
    assert (await database.get_listing_by_external_id("olx", "one"))["is_flip"] == 0

    notifier = Notifier()
    dropped = listing(price=2400)
    stale_ai = Analyzer(AIAnalysisError("must not run"))
    result = await pipeline(database, Scraper({"base": [dropped]}), stale_ai, notifier, market, configured).run()
    assert len(result) == 1 and stale_ai.analyze.await_count == 0
    assert notifier.send_alert.await_args.args[3] == 2800


@pytest.mark.asyncio
async def test_ai_failure_leaves_listing_for_future_runs(database):
    scraper, ai, notifier, market = Scraper({"base": [listing()]}), Analyzer(AIAnalysisError("bad response")), Notifier(), Market()
    assert await pipeline(database, scraper, ai, notifier, market).run() == []
    row = await database.get_listing_by_external_id("olx", "one")
    assert row and row["analysis_json"] is None and notifier.send_alert.await_count == 0


@pytest.mark.asyncio
async def test_telegram_failure_does_not_mark_sent_and_unsent_retry_sends(database):
    item = listing()
    scraper, ai, failing, market = Scraper({"base": [item]}), Analyzer(analysis()), Notifier(RuntimeError("down")), Market()
    await pipeline(database, scraper, ai, failing, market).run()
    row = await database.get_listing_by_external_id("olx", "one")
    assert row["is_sent"] == 0

    retry = Notifier()
    await pipeline(database, Scraper({"base": []}), Analyzer(analysis()), retry, market).run()
    assert retry.send_alert.await_count == 1
    assert (await database.get_listing(row["id"]))["is_sent"] == 1


@pytest.mark.asyncio
async def test_details_are_only_fetched_when_description_missing_and_failures_skip(database):
    rich = listing("rich")
    missing = listing("missing", description=None)
    scraper, ai, notifier, market = Scraper({"base": [rich, missing]}), Analyzer(analysis()), Notifier(), Market()
    await pipeline(database, scraper, ai, notifier, market).run()
    assert scraper.fetch_details.await_count == 1 and ai.analyze.await_count == 2

    bad = Scraper({"base": [listing("bad", description=None)]})
    bad.detail_error = ScraperError("detail unavailable")
    await pipeline(database, bad, Analyzer(analysis()), Notifier(), market).run()
    assert (await database.get_listing_by_external_id("olx", "bad"))["analysis_json"] is None


@pytest.mark.asyncio
async def test_scraper_block_stops_remaining_queries(database):
    scraper, ai, notifier, market = Scraper({"a": ScraperBlockedError("blocked"), "b": [listing()]}), Analyzer(analysis()), Notifier(), Market()
    result = await pipeline(database, scraper, ai, notifier, market).run(queries=["a", "b"])
    assert result == [] and scraper.search.await_count == 1


@pytest.mark.asyncio
async def test_malformed_stored_analysis_is_skipped_safely(database):
    ident, _ = await database.upsert_listing(listing())
    await database._conn.execute("UPDATE listings SET is_flip=1, analysis_json='bad', evaluation_json='bad' WHERE id=?", (ident,))
    await database._conn.commit()
    notifier = Notifier()
    await pipeline(database, Scraper({"base": []}), Analyzer(analysis()), notifier, Market()).run()
    notifier.send_alert.assert_not_awaited()


def benchmark(price: int, sample_size: int = 3) -> MarketPrice:
    return MarketPrice(model="iPhone 14", storage_gb=128, condition="good", min_price=price - 100, median_price=price, avg_price=price, max_price=price + 100, sample_size=sample_size)


@pytest.mark.asyncio
async def test_pre_ai_ranking_moves_later_high_discount_listing_to_first(database):
    first, bargain = listing("first", 2400), listing("bargain", 1800)
    ai = Analyzer(analysis())
    worker = pipeline(database, Scraper({"base": [first, bargain]}), ai, Notifier(), Market(), benchmark=SelectiveBenchmark({"first": benchmark(2500), "bargain": benchmark(2500)}))
    await worker.run(limit=1)
    assert ai.analyze.await_args.args[0].external_id == "bargain"
    assert (worker.stats.market_eligible_total, worker.stats.ranked_for_ai) == (2, 1)


@pytest.mark.asyncio
async def test_pre_ai_ranking_uses_sample_size_then_stable_original_order(database):
    first, deeper_sample = listing("first", 2000), listing("deeper", 2000)
    ai = Analyzer(analysis())
    worker = pipeline(database, Scraper({"base": [first, deeper_sample]}), ai, Notifier(), Market(), benchmark=SelectiveBenchmark({"first": benchmark(2500, 3), "deeper": benchmark(2500, 5)}))
    await worker.run(limit=1)
    assert ai.analyze.await_args.args[0].external_id == "deeper"


@pytest.mark.asyncio
async def test_no_market_and_zero_asking_price_are_not_ranked_or_divided_by_zero(database):
    class EmptyMarket:
        def lookup_for_listing(self, item): return None
        def lookup_for_device(self, device): return None
    zero, no_market, eligible = listing("zero", 0), listing("none", 2000), listing("eligible", 2000)
    ai = Analyzer(analysis())
    worker = pipeline(database, Scraper({"base": [zero, no_market, eligible]}), ai, Notifier(), EmptyMarket(), configured=settings(min_sanity_price_pln=0), benchmark=SelectiveBenchmark({"zero": benchmark(2500), "eligible": benchmark(2500)}))
    await worker.run(limit=1)
    assert ai.analyze.await_args.args[0].external_id == "eligible"
    assert worker.stats.market_unavailable == 1 and worker.stats.market_eligible_total == 2


@pytest.mark.asyncio
async def test_pre_ai_ranking_does_not_change_final_scorer_math(database):
    expensive, cheap = listing("expensive", 2400), listing("cheap", 1800)
    scorer = SpyScorer(FlipScorer(settings()).evaluate(cheap, analysis()))
    worker = pipeline(database, Scraper({"base": [expensive, cheap]}), Analyzer(analysis()), Notifier(), Market(), benchmark=SelectiveBenchmark({"expensive": benchmark(2500), "cheap": benchmark(2500)}), scorer=scorer)
    await worker.run(limit=1)
    scored_listing, _, scored_market, _ = scorer.calls[0]
    assert scored_listing.external_id == "cheap" and scored_market.median_price == 2500


@pytest.mark.asyncio
async def test_ai_delay_is_between_requests_only(monkeypatch, database):
    sleeps = AsyncMock()
    monkeypatch.setattr("app.pipeline.asyncio.sleep", sleeps)
    first, second = listing("first"), listing("second")
    worker = pipeline(database, Scraper({"base": [first, second]}), Analyzer(analysis()), Notifier(), Market(), configured=settings(ai_request_delay_seconds=4), benchmark=SelectiveBenchmark({"first": benchmark(2500), "second": benchmark(2500)}))
    await worker.run(limit=2)
    sleeps.assert_awaited_once_with(4)


@pytest.mark.asyncio
async def test_terminal_ai_429_does_not_stop_following_ranked_listing(database):
    first, second = listing("first"), listing("second")
    ai = Analyzer(analysis())
    ai.analyze = AsyncMock(side_effect=[AIAnalysisError("HTTP 429"), analysis()])
    worker = pipeline(database, Scraper({"base": [first, second]}), ai, Notifier(), Market(), benchmark=SelectiveBenchmark({"first": benchmark(2500), "second": benchmark(2400)}))
    await worker.run(limit=2)
    assert ai.analyze.await_count == 2 and worker.stats.errors == 1 and worker.stats.analyzed == 1


@pytest.mark.asyncio
async def test_evaluation_log_reports_result_without_changing_scorer_output(caplog, database):
    caplog.set_level("INFO")
    item = listing("logged", 2000)
    expected = FlipScorer(settings()).evaluate(item, analysis())
    scorer = SpyScorer(expected)
    worker = pipeline(database, Scraper({"base": [item]}), Analyzer(analysis()), Notifier(), Market(), scorer=scorer)
    result = await worker.run()
    assert result == [expected]
    assert "Evaluation: external_id=logged" in caplog.text
    assert "deterministic_resale=" in caplog.text


def saved_evaluation(*, version=1, candidate=False, score=65.2) -> FlipEvaluation:
    return FlipEvaluation(scoring_version=version, flip_score=score, estimated_profit=700, margin_pct=107.7, resale_price_used=2700, resale_source="dynamic_market", resale_confidence_used=.55, market_sample_size=3, is_flip_candidate=candidate)


async def seed_analyzed(database, item, evaluation):
    listing_id, _ = await database.upsert_listing(item)
    await database.update_listing_analysis(listing_id, analysis().device_info, analysis(), evaluation)
    return listing_id


def current_candidate_scorer() -> SpyScorer:
    return SpyScorer(FlipEvaluation(scoring_version=SCORING_VERSION, flip_score=75.2, estimated_profit=700, margin_pct=107.7, resale_price_used=2700, resale_source="dynamic_market", resale_confidence_used=.55, market_sample_size=3, is_flip_candidate=True))


@pytest.mark.asyncio
async def test_stale_current_listing_rescores_stored_analysis_without_ai_and_saves_version(database):
    item = listing("stale")
    await seed_analyzed(database, item, saved_evaluation())
    ai, scorer = Analyzer(AIAnalysisError("must not run")), current_candidate_scorer()
    worker = pipeline(database, Scraper({"base": [item]}), ai, Notifier(), Market(), benchmark=Benchmark(Market().preliminary), scorer=scorer)
    await worker.run(limit=1)
    row = await database.get_listing_by_external_id("olx", "stale")
    assert ai.analyze.await_count == 0 and scorer.calls and worker.stats.stale_evaluations == worker.stats.rescored == 1
    assert json.loads(row["evaluation_json"])["scoring_version"] == SCORING_VERSION


@pytest.mark.asyncio
async def test_current_scoring_version_unchanged_listing_skips(database):
    item = listing("current")
    await seed_analyzed(database, item, saved_evaluation(version=SCORING_VERSION))
    scorer = current_candidate_scorer()
    worker = pipeline(database, Scraper({"base": [item]}), Analyzer(AIAnalysisError("must not run")), Notifier(), Market(), benchmark=Benchmark(Market().preliminary), scorer=scorer)
    await worker.run()
    assert scorer.calls == [] and worker.stats.known_analyzed_unchanged == 1 and worker.stats.rescored == 0


@pytest.mark.asyncio
async def test_missing_scoring_version_is_treated_as_stale(database):
    item = listing("legacy")
    listing_id = await seed_analyzed(database, item, saved_evaluation())
    raw = saved_evaluation().model_dump(); raw.pop("scoring_version")
    await database._conn.execute("UPDATE listings SET evaluation_json=? WHERE id=?", (json.dumps(raw), listing_id))
    await database._conn.commit()
    worker = pipeline(database, Scraper({"base": [item]}), Analyzer(AIAnalysisError("must not run")), Notifier(), Market(), benchmark=Benchmark(Market().preliminary), scorer=current_candidate_scorer())
    await worker.run()
    assert worker.stats.stale_evaluations == worker.stats.rescored == 1


@pytest.mark.asyncio
async def test_stale_rescore_does_not_consume_limit_or_send_duplicate_sent_alert(database):
    stale, fresh = listing("stale"), listing("fresh")
    stale_id = await seed_analyzed(database, stale, saved_evaluation(candidate=True))
    await database.mark_sent(stale_id)
    ai, notifier = Analyzer(analysis()), Notifier()
    worker = pipeline(database, Scraper({"base": [stale, fresh]}), ai, notifier, Market(), benchmark=Benchmark(Market().preliminary), scorer=current_candidate_scorer())
    await worker.run(limit=1)
    assert worker.stats.rescored == 1 and ai.analyze.await_count == 1
    assert notifier.send_alert.await_count == 1  # only the fresh candidate, never stale duplicate


@pytest.mark.asyncio
async def test_stale_false_to_true_sends_initial_alert_and_no_market_retries(database):
    item = listing("transition")
    await seed_analyzed(database, item, saved_evaluation(candidate=False))
    notifier = Notifier()
    worker = pipeline(database, Scraper({"base": [item]}), Analyzer(AIAnalysisError("must not run")), notifier, Market(), benchmark=Benchmark(Market().preliminary), scorer=current_candidate_scorer())
    await worker.run()
    row = await database.get_listing_by_external_id("olx", "transition")
    assert notifier.send_alert.await_count == 1 and notifier.send_alert.await_args.args[3] is None
    assert row["is_sent"] == 1 and worker.stats.rescored_alerts == 1

    retry = listing("retry")
    await seed_analyzed(database, retry, saved_evaluation())
    class EmptyMarket:
        def lookup_for_listing(self, item): return None
        def lookup_for_device(self, device): return None
    no_market = pipeline(database, Scraper({"base": [retry]}), Analyzer(AIAnalysisError("must not run")), Notifier(), EmptyMarket(), benchmark=Benchmark(None), scorer=current_candidate_scorer())
    await no_market.run()
    retry_row = await database.get_listing_by_external_id("olx", "retry")
    assert no_market.stats.stale_evaluations == 1 and no_market.stats.rescored == 0
    assert json.loads(retry_row["evaluation_json"])["scoring_version"] == 1


@pytest.mark.asyncio
async def test_stale_listing_absent_from_current_snapshot_is_not_rescored(database):
    item = listing("absent")
    await seed_analyzed(database, item, saved_evaluation())
    worker = pipeline(database, Scraper({"base": []}), Analyzer(AIAnalysisError("must not run")), Notifier(), Market(), benchmark=Benchmark(Market().preliminary), scorer=current_candidate_scorer())
    await worker.run()
    assert worker.stats.stale_evaluations == worker.stats.rescored == 0
