from app.models import Listing
from app.services.market_benchmark import MIN_BENCHMARK_SAMPLE, MarketBenchmarkBuilder


def item(identifier, price, model="iphone-15-pro", storage="128gb", state="used", currency="PLN", title="iPhone 15 Pro 128GB"):
    attributes = {"phonemodel": model, "state": state} if model else {"state": state}
    if storage is not None: attributes["builtinmemory_phones"] = storage
    return Listing(source="olx", external_id=str(identifier), url=f"https://x/{identifier}", title=title, price=price, currency=currency, attributes=attributes)


def test_groups_model_storage_condition_and_currency_separately():
    universe = [item("a", 100), item("b", 110), item("c", 120), item("d", 200, storage="256gb"), item("e", 210, storage="256gb"), item("f", 220, storage="256gb"), item("g", 300, state="new"), item("h", 310, state="new"), item("i", 320, state="new"), item("j", 400, currency="EUR"), item("k", 410, currency="EUR"), item("l", 420, currency="EUR")]
    markets = MarketBenchmarkBuilder().build(universe)
    assert {(m.storage_gb, m.condition, m.currency) for m in markets} == {(128, "good", "PLN"), (256, "good", "PLN"), (128, "new", "PLN"), (128, "good", "EUR")}


def test_minimum_sample_stats_and_median_diagnostics():
    builder = MarketBenchmarkBuilder()
    market = builder.build([item("a", 100), item("b", 200), item("c", 300)])[0]
    assert (market.min_price, market.median_price, market.avg_price, market.max_price, market.sample_size) == (100, 200, 200, 300, MIN_BENCHMARK_SAMPLE)
    assert builder.diagnostics[0].median_price == 200
    assert MarketBenchmarkBuilder().build([item("a", 100), item("b", 200)]) == []


def test_iqr_removes_only_large_group_outlier_and_small_groups_keep_values():
    builder = MarketBenchmarkBuilder()
    market = builder.build([item(str(n), price) for n, price in enumerate([100, 101, 102, 103, 10000])])[0]
    assert (market.min_price, market.max_price, market.sample_size) == (100, 103, 4)
    assert builder.diagnostics[0].removed_outliers == 1
    small = MarketBenchmarkBuilder().build([item(str(n), price) for n, price in enumerate([100, 101, 10000])])[0]
    assert small.max_price == 10000


def test_title_storage_fallback_and_others_fallback():
    markets = MarketBenchmarkBuilder().build([item("a", 100, storage=None), item("b", 110, storage="others"), item("c", 120)])
    assert markets[0].storage_gb == 128


def test_leave_one_out_excludes_current_listing_and_can_be_insufficient():
    universe = [item("a", 100), item("b", 110), item("c", 120), item("d", 1000)]
    builder = MarketBenchmarkBuilder()
    market = builder.lookup_for_listing(universe[-1], universe)
    assert market and market.avg_price == 110 and market.sample_size == 3
    assert builder.lookup_for_listing(universe[0], universe[:3]) is None


def test_refurbished_is_a_separate_exact_market_segment():
    refurbished = [item(f"r{n}", 100 + n, state="refurbished") for n in range(3)]
    used = [item(f"u{n}", 200 + n, state="used") for n in range(3)]
    markets = MarketBenchmarkBuilder().build(refurbished + used)
    assert {(market.condition, market.sample_size) for market in markets} == {("refurbished", 3), ("good", 3)}
    assert MarketBenchmarkBuilder().lookup_for_listing(refurbished[0], refurbished) is None
