from __future__ import annotations
import json
import pytest
from app.models import DeviceInfo, Listing
from app.services.market_data import MarketDataProvider

def row(model="iPhone 15 Pro",storage=256,condition="good",price=3000): return {"model":model,"storage_gb":storage,"condition":condition,"min_price":min(2700,price),"avg_price":price,"max_price":max(3400,price),"sample_size":2,"currency":"PLN"}
async def provider(tmp_path,rows):
    path=tmp_path/"market.json"; path.write_text(json.dumps(rows),encoding="utf-8"); value=MarketDataProvider(str(path)); await value.load(); return value

@pytest.mark.asyncio
async def test_load_lookup_and_normalization(tmp_path):
    p=await provider(tmp_path,[row(),row("iPhone 15 Pro",256,"excellent",3100)])
    assert p.lookup(" iphone   15 PRO ",256,"GOOD").avg_price==3000
    assert p.lookup("iPhone 15 Pro",256,"excellent").avg_price==3100
    assert p.lookup("x",256,"good") is None

@pytest.mark.asyncio
async def test_load_errors_and_missing(tmp_path,caplog):
    p=MarketDataProvider(str(tmp_path/"missing.json")); await p.load(); assert not p._index and "missing" in caplog.text
    path=tmp_path/"bad.json"; path.write_text("{}")
    with pytest.raises(ValueError): await MarketDataProvider(str(path)).load()
    path.write_text("[")
    with pytest.raises(ValueError): await MarketDataProvider(str(path)).load()
    path.write_text(json.dumps([row(),row()]))
    with pytest.raises(ValueError): await MarketDataProvider(str(path)).load()

@pytest.mark.asyncio
async def test_extraction_listing_and_device_fallbacks(tmp_path):
    p=await provider(tmp_path,[row(),row("iPhone 15 Pro Max",512,"good",5000),row("iPhone 15 Pro",256,"excellent",3200)])
    assert p.extract_device_hint("Apple iPhone 15 Pro Max 512 GB") == ("iPhone 15 Pro Max",512)
    assert p.extract_device_hint("IPHONE 13 mini 1TB") == ("iPhone 13 Mini",1024)
    assert p.extract_device_hint("battery 100%") == (None,None)
    l=Listing(source="olx",external_id="1",url="x",title="iPhone 15 Pro 256GB",price=1)
    assert p.lookup_for_listing(l).avg_price==3000
    assert p.lookup_for_device(DeviceInfo(model="iPhone 15 Pro",storage_gb=256,condition="excellent")).avg_price==3200
    assert p.lookup_for_device(DeviceInfo(model="iPhone 15 Pro Max",storage_gb=512,condition="fair")).avg_price==5000
    assert p.lookup_for_device(DeviceInfo(model="iPhone 15 Pro",storage_gb=256,condition="damaged")) is None
