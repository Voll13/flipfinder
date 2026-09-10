from app.config import Settings
from app.models import AIAnalysis,DeviceInfo,Listing,MarketPrice
from app.scoring import FlipScorer
from app.services.resale_estimator import ResaleEstimate
def listing(price=2000):return Listing(source="olx",external_id="1",url="x",title="iPhone",price=price)
def analysis(**kw):
 d=kw.pop("device_info",DeviceInfo(condition="good",battery_health=91)); values={"device_info":d,"estimated_resale_price":3000,"resale_confidence":.9,"fraud_risk":.1,"summary":"x"}; values.update(kw); return AIAnalysis(**values)
def market():return MarketPrice(model="iPhone",storage_gb=128,condition="good",min_price=2200,avg_price=3000,max_price=3500,sample_size=10)
def test_profit_fees_market_and_determinism():
 s=FlipScorer(Settings(_env_file=None,marketplace_fee_pct=10)); one=s.evaluate(listing(),analysis(),market()); two=s.evaluate(listing(),analysis(),market())
 assert one.estimated_profit==700 and one.fees_estimate==300 and one==two and 0<=one.flip_score<=100
def test_hard_stops_risk_and_zero():
 s=FlipScorer(Settings(_env_file=None)); assert not s.evaluate(listing(),analysis(device_info=DeviceInfo(icloud_locked=True)),market()).is_flip_candidate
 assert not s.evaluate(listing(),analysis(fraud_risk=.9),market()).is_flip_candidate
 assert not s.evaluate(listing(0),analysis(),market()).is_flip_candidate
def test_components_and_reasons():
 s=FlipScorer(Settings(_env_file=None)); high=s.evaluate(listing(1800),analysis(),market()); low=s.evaluate(listing(2800),analysis(),market())
 assert high.flip_score>low.flip_score and any("below market" in x for x in high.reasons)
 assert s.evaluate(listing(),analysis(device_info=DeviceInfo(condition="damaged")),None).is_flip_candidate is False
 assert not s.evaluate(listing(),analysis(red_flags=["no IMEI mentioned"]),None).is_flip_candidate

def test_deterministic_resale_overrides_llm_and_is_recorded():
 estimate=ResaleEstimate(price=2800,confidence=.55,source="dynamic_market",base_price=2800,adjustments=[],market_sample_size=3,market_min=2500,market_median=2800,market_avg=2800,market_max=3000)
 result=FlipScorer(Settings(_env_file=None,marketplace_fee_pct=10)).evaluate(listing(),analysis(),market(),estimate)
 assert (result.resale_price_used,result.resale_source,result.resale_confidence_used,result.estimated_profit)==(2800,"dynamic_market",.55,520)

def test_llm_fallback_remains_backward_compatible():
 result=FlipScorer(Settings(_env_file=None)).evaluate(listing(),analysis())
 assert result.resale_source=="llm_fallback" and result.resale_price_used==3000

def test_explain_components_sum_to_the_actual_score_without_changing_evaluation():
 s=FlipScorer(Settings(_env_file=None)); item=listing(1000); reviewed=analysis()
 before=s.evaluate(item,reviewed,market())
 breakdown=s.explain(item,reviewed,market())
 after=s.evaluate(item,reviewed,market())
 expected=(breakdown.profitability_component+breakdown.market_discount_component-breakdown.suspicious_low_price_penalty+breakdown.confidence_component+breakdown.condition_component+breakdown.positive_component-breakdown.risk_penalty-breakdown.red_flag_penalty)
 assert breakdown.score_before_clamp==expected
 assert breakdown.final_score==before.flip_score==after.flip_score
 assert breakdown.suspicious_low_price_penalty==5

def test_explain_reports_hard_stop_without_altering_candidate_decision():
 s=FlipScorer(Settings(_env_file=None)); reviewed=analysis(device_info=DeviceInfo(icloud_locked=True))
 breakdown=s.explain(listing(),reviewed,market())
 assert breakdown.hard_stop_reason=="iCloud lock"
 assert breakdown.is_flip_candidate==s.evaluate(listing(),reviewed,market()).is_flip_candidate is False

def diagnostic_case(identifier, asking, resale, confidence, current_market, device, fraud=.1):
 item=Listing(source="olx",external_id=identifier,url=f"https://x/{identifier}",title="iPhone diagnostic",price=asking)
 reviewed=AIAnalysis(device_info=device,estimated_resale_price=resale,resale_confidence=.8,fraud_risk=fraud,summary="offline",positive_signals=["one","two","three"])
 estimate=ResaleEstimate(price=resale,confidence=confidence,source="dynamic_market",base_price=current_market.median_price or current_market.avg_price,adjustments=[],market_sample_size=current_market.sample_size,market_min=current_market.min_price,market_median=current_market.median_price,market_avg=current_market.avg_price,market_max=current_market.max_price)
 return item,reviewed,current_market,estimate

def test_valid_n3_and_n4_market_discount_has_no_sample_haircut():
 s=FlipScorer(Settings(_env_file=None))
 for sample_size in (3,4):
  current=MarketPrice(model="iPhone",storage_gb=128,condition="good",min_price=1000,median_price=2000,avg_price=2000,max_price=2200,sample_size=sample_size)
  item,reviewed,market_value,estimate=diagnostic_case(str(sample_size),1000,2000,.55,current,DeviceInfo(condition="good"))
  assert s.explain(item,reviewed,market_value,estimate).market_discount_component==20

def test_offline_a_fixture_becomes_candidate_without_package_or_battery_evidence():
 s=FlipScorer(Settings(_env_file=None))
 current=MarketPrice(model="iPhone 13 Pro",storage_gb=128,condition="good",min_price=1250,median_price=1325,avg_price=1312,max_price=1350,sample_size=4)
 item,reviewed,market_value,estimate=diagnostic_case("A",650,1350,.57,current,DeviceInfo(condition="excellent",damaged=False,screen_damaged=False,icloud_locked=False,operator_locked=False),.05)
 breakdown=s.explain(item,reviewed,market_value,estimate)
 assert (breakdown.market_discount_component,breakdown.final_score,breakdown.is_flip_candidate)==(20,75.2,True)
 assert s.evaluate(item,reviewed,market_value,estimate).flip_score==breakdown.final_score

def test_offline_b_hard_stop_and_c_actual_score_are_preserved():
 s=FlipScorer(Settings(_env_file=None))
 b_market=MarketPrice(model="iPhone 13",storage_gb=256,condition="good",min_price=950,median_price=1199,avg_price=1221,max_price=1499,sample_size=7)
 b=diagnostic_case("B",700,803,.70,b_market,DeviceInfo(condition="good",battery_health=96,screen_damaged=True),.1)
 assert s.explain(*b).is_flip_candidate is False and s.explain(*b).hard_stop_reason=="screen damaged"
 c_market=MarketPrice(model="iPhone 13",storage_gb=128,condition="good",min_price=700,median_price=999,avg_price=1005,max_price=1300,sample_size=17)
 c=diagnostic_case("C",730,929,.90,c_market,DeviceInfo(condition="good",battery_health=80),.1)
 assert (s.explain(*c).final_score,s.explain(*c).is_flip_candidate)==(55.9,False)
