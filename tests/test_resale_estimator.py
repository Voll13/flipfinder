from app.models import AIAnalysis, DeviceInfo, Listing, MarketPrice
from app.services.resale_estimator import ResaleEstimator


def listing(price=2200):
    return Listing(source="olx", external_id=str(price), url="https://x", title="iPhone 15 Pro", price=price)


def market(**changes):
    data = dict(model="iPhone 15 Pro", storage_gb=128, condition="good", min_price=2000, median_price=2500, avg_price=2600, max_price=2700, sample_size=5)
    data.update(changes)
    return MarketPrice(**data)


def analysis(**device_changes):
    device = {"condition": "good", "battery_health": 92}
    device.update(device_changes)
    return AIAnalysis(device_info=DeviceInfo(**device), estimated_resale_price=9999, resale_confidence=.1, fraud_risk=.1, summary="ok")


def estimate(price=2200, current_market=None, current_analysis=None):
    return ResaleEstimator().estimate(listing(price), current_analysis or analysis(), current_market or market(), "dynamic_market")


def test_median_is_preferred_and_avg_is_fallback():
    assert estimate().base_price == 2500 and estimate().price == 2500
    fallback = estimate(current_market=market(median_price=None))
    assert fallback.base_price == 2600 and fallback.price == 2600


def test_asking_price_does_not_change_resale():
    assert estimate(1500).price == estimate(2200).price


def test_condition_adjustments_are_transparent():
    assert estimate(current_analysis=analysis(condition="excellent")).price == 2575
    assert estimate(current_analysis=analysis(condition="good")).price == 2500
    assert estimate(current_analysis=analysis(condition="fair")).price == 2250
    assert estimate(current_analysis=analysis(condition="damaged")).price < 2000


def test_battery_and_package_adjustments():
    assert estimate(current_analysis=analysis(battery_health=95)).price == 2550
    assert estimate(current_analysis=analysis(battery_health=87)).price == 2425
    assert estimate(current_analysis=analysis(battery_health=79)).price == 2200
    bundled = estimate(current_analysis=analysis(has_box=True, has_receipt=True, has_warranty=True))
    assert bundled.price == 2600 and set(bundled.adjustments) == {"box +1%", "receipt +1%", "warranty +2%"}


def test_positive_cap_market_max_and_fair_can_be_below_market_min():
    capped = estimate(current_market=market(max_price=3000), current_analysis=analysis(condition="new", battery_health=99, has_box=True, has_receipt=True, has_warranty=True))
    assert capped.price == 2750
    boosted = estimate(current_market=market(avg_price=2500, max_price=2550), current_analysis=analysis(condition="excellent", battery_health=99, has_box=True, has_receipt=True, has_warranty=True))
    assert boosted.price == 2550
    assert estimate(current_market=market(min_price=2400), current_analysis=analysis(condition="fair", battery_health=79)).price < 2400


def test_confidence_missing_market_and_repeatability():
    assert estimate(current_market=market(sample_size=3)).confidence == .55
    assert estimate(current_market=market(sample_size=4)).confidence == .60
    assert estimate(current_market=market(sample_size=8)).confidence == .80
    assert estimate(current_market=market(sample_size=15)).confidence == .90
    assert estimate(current_analysis=analysis(condition=None, battery_health=None)).confidence == .57
    assert ResaleEstimator().estimate(listing(), analysis(), None, "dynamic_market") is None
    assert estimate() == estimate()


def test_refurbished_market_does_not_add_excellent_condition_premium():
    result = estimate(current_market=market(condition="refurbished"), current_analysis=analysis(condition="excellent"))
    assert result.price == result.base_price and not any("condition excellent" in item for item in result.adjustments)
