from __future__ import annotations
import json, sqlite3
from datetime import datetime, timedelta, timezone
import pytest
import pytest_asyncio
from app.models import AIAnalysis, DeviceInfo, FlipEvaluation, Listing
from app.storage.database import Database

def listing(price:int=1000, external_id:str="x") -> Listing:
    return Listing(source="olx",external_id=external_id,url="https://x",title="Żółty iPhone",price=price,location="Łódź",photo_urls=["https://p"],attributes={"phonemodel":"iphone-15-pro"})
def market_listing(identifier:str, price:int, storage:str="128gb", state:str="used") -> Listing:
    return Listing(source="olx",external_id=identifier,url=f"https://{identifier}",title="iPhone 15 Pro",price=price,currency="PLN",attributes={"phonemodel":"iphone-15-pro","builtinmemory_phones":storage,"state":state})
@pytest_asyncio.fixture
async def db(tmp_path):
    async with Database(str(tmp_path/"test.db")) as value: yield value

@pytest.mark.asyncio
async def test_lifecycle_and_guard(tmp_path):
    value=Database(str(tmp_path/"x.db"))
    with pytest.raises(RuntimeError): await value.exists("o","x")
    await value.connect(); await value.init_schema(); await value.close(); await value.close()

@pytest.mark.asyncio
async def test_insert_exists_and_duplicate(db:Database):
    ident=await db.insert_listing(listing())
    assert ident and await db.exists("olx","x") and not await db.exists("olx","none")
    row=await db.get_listing(ident)
    assert row and row["first_seen_at"] and row["last_seen_at"] and json.loads(row["photo_urls"]) == ["https://p"] and json.loads(row["attributes_json"]) == {"phonemodel":"iphone-15-pro"}
    assert len(await db.get_price_history(ident)) == 1
    with pytest.raises(ValueError): await db.insert_listing(listing())

@pytest.mark.asyncio
async def test_upsert_history_touch_and_previous(db:Database):
    ident,new=await db.upsert_listing(listing(1000)); assert new
    same,new=await db.upsert_listing(listing(1000)); assert same==ident and not new and len(await db.get_price_history(ident))==1
    await db.upsert_listing(listing(900)); await db.touch_listing(listing(800))
    assert [x["price"] for x in await db.get_price_history(ident)] == [1000,900,800]
    assert await db.get_previous_price(ident)==900
    await db.mark_sent(ident); await db.touch_listing(listing(800)); assert (await db.get_listing(ident))["is_sent"]==1

@pytest.mark.asyncio
async def test_analysis_unsent_and_inactive(db:Database):
    a,_=await db.upsert_listing(listing(1000,"a")); b,_=await db.upsert_listing(listing(1000,"b"))
    info=DeviceInfo(model="iPhone",storage_gb=128)
    analysis=AIAnalysis(device_info=info,estimated_resale_price=1500,resale_confidence=.8,fraud_risk=.1,summary="ok")
    good=FlipEvaluation(flip_score=90,estimated_profit=100,margin_pct=10,is_flip_candidate=True)
    bad=FlipEvaluation(flip_score=10,estimated_profit=0,margin_pct=0,is_flip_candidate=False)
    await db.update_listing_analysis(a,info,analysis,good); await db.update_listing_analysis(b,info,analysis,bad)
    row=await db.get_listing(a); assert row and row["is_flip"]==1 and json.loads(row["analysis_json"])["summary"]=="ok"
    assert [x["id"] for x in await db.get_unsent_flips()] == [a]
    await db.mark_sent(a); assert await db.get_unsent_flips()==[]
    cutoff=datetime.now(timezone.utc)+timedelta(seconds=1); assert await db.mark_inactive_before(cutoff)==2
    assert (await db.get_listing_by_external_id("olx","a"))["is_active"]==0

@pytest.mark.asyncio
async def test_old_schema_migrates_attributes_column_and_keeps_old_rows(tmp_path):
    path=tmp_path/"legacy.db"
    conn=sqlite3.connect(path)
    conn.execute("CREATE TABLE listings (id INTEGER PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL, price INTEGER NOT NULL, currency TEXT NOT NULL, location TEXT, seller_type TEXT, published_at TEXT, description TEXT, photo_urls TEXT, device_info TEXT, analysis_json TEXT, evaluation_json TEXT, flip_score REAL, is_flip INTEGER NOT NULL DEFAULT 0, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1, is_sent INTEGER NOT NULL DEFAULT 0, sent_at TEXT, UNIQUE(source,external_id))")
    conn.execute("INSERT INTO listings(source,external_id,url,title,price,currency,first_seen_at,last_seen_at) VALUES('olx','old','https://old','Old',100,'PLN','now','now')")
    conn.commit(); conn.close()
    async with Database(str(path)) as value:
        row=await value.get_listing_by_external_id("olx","old")
        assert row and row["attributes_json"] is None
        ident=await value.touch_listing(listing(200,"old"))
        updated=await value.get_listing(ident)
        assert json.loads(updated["attributes_json"]) == {"phonemodel":"iphone-15-pro"}

@pytest.mark.asyncio
async def test_persistent_market_listings_upsert_recency_and_exact_attributes(db:Database):
    first=market_listing("a",2000)
    await db.upsert_market_listings([first,market_listing("b",2100,"256gb"),market_listing("c",2200,"128gb","refurbished")])
    await db.upsert_market_listings([market_listing("a",1900)])
    rows=await db.get_market_universe()
    assert await db.market_listing_count()==3
    assert {(row.external_id,row.price) for row in rows if row.external_id=="a"} == {("a",1900)}
    assert {(row.attributes.get("builtinmemory_phones"),row.attributes.get("state")) for row in rows} == {("128gb","used"),("256gb","used"),("128gb","refurbished")}
    stale=(datetime.now(timezone.utc)-timedelta(hours=73)).isoformat()
    await db._conn.execute("UPDATE market_listings SET last_seen_at=? WHERE external_id='c'",(stale,)); await db._conn.commit()
    assert {row.external_id for row in await db.get_market_universe(72)} == {"a","b"}
