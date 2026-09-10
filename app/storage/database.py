"""SQLite persistence for discovered marketplace listings."""
from __future__ import annotations

import asyncio, json
from datetime import datetime, timedelta, timezone
from typing import Any
import aiosqlite
from pydantic import BaseModel
from app.models import AIAnalysis, DeviceInfo, FlipEvaluation, Listing
from app.services.market_benchmark import market_key

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, external_id TEXT NOT NULL, url TEXT NOT NULL, title TEXT NOT NULL, price INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'PLN', location TEXT, seller_type TEXT, published_at TEXT, description TEXT, photo_urls TEXT, attributes_json TEXT, device_info TEXT, analysis_json TEXT, evaluation_json TEXT, flip_score REAL, is_flip INTEGER NOT NULL DEFAULT 0, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1, is_sent INTEGER NOT NULL DEFAULT 0, sent_at TEXT, UNIQUE(source, external_id));
CREATE TABLE IF NOT EXISTS listing_price_history (id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER NOT NULL, price INTEGER NOT NULL, currency TEXT NOT NULL DEFAULT 'PLN', recorded_at TEXT NOT NULL, FOREIGN KEY(listing_id) REFERENCES listings(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_price_history_listing ON listing_price_history(listing_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_listings_source_external ON listings(source, external_id);
CREATE INDEX IF NOT EXISTS idx_listings_flip_score ON listings(flip_score);
CREATE INDEX IF NOT EXISTS idx_listings_last_seen ON listings(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_listings_sent ON listings(is_sent, is_flip);
CREATE TABLE IF NOT EXISTS market_listings (id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, external_id TEXT NOT NULL, url TEXT, title TEXT NOT NULL, price INTEGER NOT NULL, currency TEXT NOT NULL, model TEXT, storage_gb INTEGER, market_condition TEXT, location TEXT, first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, is_active INTEGER NOT NULL DEFAULT 1, UNIQUE(source, external_id));
CREATE INDEX IF NOT EXISTS idx_market_listings_key ON market_listings(model, storage_gb, market_condition, currency);
CREATE INDEX IF NOT EXISTS idx_market_listings_last_seen ON market_listings(last_seen_at);
CREATE INDEX IF NOT EXISTS idx_market_listings_active ON market_listings(is_active);
CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS monitoring_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT NOT NULL, finished_at TEXT, duration_seconds REAL, current_listings INTEGER NOT NULL DEFAULT 0, persistent_market_rows INTEGER NOT NULL DEFAULT 0, query_candidates INTEGER NOT NULL DEFAULT 0, market_available INTEGER NOT NULL DEFAULT 0, market_unavailable INTEGER NOT NULL DEFAULT 0, ai_analysed INTEGER NOT NULL DEFAULT 0, flip_candidates INTEGER NOT NULL DEFAULT 0, alerts_sent INTEGER NOT NULL DEFAULT 0, errors INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, error_message TEXT);
CREATE INDEX IF NOT EXISTS idx_monitoring_runs_started ON monitoring_runs(started_at DESC);
CREATE TABLE IF NOT EXISTS market_benchmark_history (id INTEGER PRIMARY KEY AUTOINCREMENT, monitoring_run_id INTEGER NOT NULL, captured_at TEXT NOT NULL, model TEXT NOT NULL, storage_gb INTEGER NOT NULL, condition TEXT NOT NULL, currency TEXT NOT NULL, sample_size INTEGER NOT NULL, min_price INTEGER NOT NULL, median_price INTEGER, avg_price INTEGER NOT NULL, max_price INTEGER NOT NULL, source TEXT NOT NULL DEFAULT 'dynamic', UNIQUE(monitoring_run_id,model,storage_gb,condition,currency), FOREIGN KEY(monitoring_run_id) REFERENCES monitoring_runs(id) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS idx_market_benchmark_history_key ON market_benchmark_history(model,storage_gb,condition,captured_at DESC);
"""
def _utc_now_iso() -> str: return datetime.now(timezone.utc).isoformat()
def _json_dumps(value: object) -> str: return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
def _model_to_json(model: BaseModel | None) -> str | None: return _json_dumps(model.model_dump(mode="json")) if model else None

class Database:
    def __init__(self, db_path: str) -> None: self.db_path=db_path; self._conn: aiosqlite.Connection|None=None; self._lock=asyncio.Lock()
    def _require_connection(self) -> aiosqlite.Connection:
        if self._conn is None: raise RuntimeError("Database is not connected")
        return self._conn
    async def connect(self) -> None:
        if self._conn is None:
            self._conn=await aiosqlite.connect(self.db_path); self._conn.row_factory=aiosqlite.Row
            await self._conn.execute("PRAGMA foreign_keys = ON")
            if self.db_path != ":memory:": await self._conn.execute("PRAGMA journal_mode = WAL")
    async def close(self) -> None:
        if self._conn: await self._conn.close(); self._conn=None
    async def __aenter__(self) -> Database: await self.connect(); await self.init_schema(); return self
    async def __aexit__(self,*args: object) -> None: await self.close()
    async def init_schema(self) -> None:
        conn=self._require_connection(); await conn.executescript(SCHEMA)
        columns={row["name"] for row in await (await conn.execute("PRAGMA table_info(listings)")).fetchall()}
        if "attributes_json" not in columns: await conn.execute("ALTER TABLE listings ADD COLUMN attributes_json TEXT")
        if "review_status" not in columns: await conn.execute("ALTER TABLE listings ADD COLUMN review_status TEXT NOT NULL DEFAULT 'new'")
        if "review_note" not in columns: await conn.execute("ALTER TABLE listings ADD COLUMN review_note TEXT")
        if "reviewed_at" not in columns: await conn.execute("ALTER TABLE listings ADD COLUMN reviewed_at TEXT")
        if "favorite" not in columns: await conn.execute("ALTER TABLE listings ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_review ON listings(review_status, favorite, last_seen_at DESC)")
        await conn.commit()
    async def exists(self,source:str,external_id:str)->bool: return await self.get_listing_id(source,external_id) is not None
    async def get_listing_id(self,source:str,external_id:str)->int|None:
        row=await (await self._require_connection().execute("SELECT id FROM listings WHERE source=? AND external_id=?",(source,external_id))).fetchone(); return int(row["id"]) if row else None
    def _values(self,l:Listing)->tuple[Any,...]: return (l.url,l.title,l.price,l.currency,l.location,l.seller_type,l.published_at.isoformat() if l.published_at else None,l.description,_json_dumps(l.photo_urls),_json_dumps(l.attributes))
    async def insert_listing(self, listing:Listing)->int:
        async with self._lock:
            if await self.exists(listing.source,listing.external_id): raise ValueError("Listing already exists")
            now=_utc_now_iso(); c=self._require_connection()
            async with c.execute("INSERT INTO listings(source,external_id,url,title,price,currency,location,seller_type,published_at,description,photo_urls,attributes_json,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(listing.source,listing.external_id,*self._values(listing),now,now)) as cur: ident=int(cur.lastrowid)
            await c.execute("INSERT INTO listing_price_history(listing_id,price,currency,recorded_at) VALUES(?,?,?,?)",(ident,listing.price,listing.currency,now)); await c.commit(); return ident
    async def upsert_listing(self,listing:Listing)->tuple[int,bool]:
        async with self._lock:
            ident=await self.get_listing_id(listing.source,listing.external_id)
            if ident is None:
                # lock is re-entrant only at this level; duplicate insert logic inline
                now=_utc_now_iso(); c=self._require_connection()
                async with c.execute("INSERT INTO listings(source,external_id,url,title,price,currency,location,seller_type,published_at,description,photo_urls,attributes_json,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(listing.source,listing.external_id,*self._values(listing),now,now)) as cur: ident=int(cur.lastrowid)
                await c.execute("INSERT INTO listing_price_history(listing_id,price,currency,recorded_at) VALUES(?,?,?,?)",(ident,listing.price,listing.currency,now)); await c.commit(); return ident,True
            await self._update_existing(ident,listing); return ident,False
    async def _update_existing(self,ident:int,l:Listing)->None:
        c=self._require_connection(); row=await (await c.execute("SELECT price,currency FROM listings WHERE id=?",(ident,))).fetchone(); now=_utc_now_iso()
        await c.execute("UPDATE listings SET url=?,title=?,price=?,currency=?,location=?,seller_type=?,published_at=?,description=?,photo_urls=?,attributes_json=?,last_seen_at=?,is_active=1 WHERE id=?",(*self._values(l),now,ident))
        if row["price"] != l.price or row["currency"] != l.currency: await c.execute("INSERT INTO listing_price_history(listing_id,price,currency,recorded_at) VALUES(?,?,?,?)",(ident,l.price,l.currency,now))
        await c.commit()
    async def touch_listing(self,listing:Listing)->int:
        async with self._lock:
            ident=await self.get_listing_id(listing.source,listing.external_id)
            if ident is None:
                now=_utc_now_iso(); c=self._require_connection()
                async with c.execute("INSERT INTO listings(source,external_id,url,title,price,currency,location,seller_type,published_at,description,photo_urls,attributes_json,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(listing.source,listing.external_id,*self._values(listing),now,now)) as cur: ident=int(cur.lastrowid)
                await c.execute("INSERT INTO listing_price_history(listing_id,price,currency,recorded_at) VALUES(?,?,?,?)",(ident,listing.price,listing.currency,now)); await c.commit(); return ident
            await self._update_existing(ident,listing); return ident
    async def get_price_history(self,listing_id:int)->list[dict]: return [dict(r) for r in await (await self._require_connection().execute("SELECT * FROM listing_price_history WHERE listing_id=? ORDER BY recorded_at ASC,id ASC",(listing_id,))).fetchall()]
    async def get_previous_price(self,listing_id:int)->int|None:
        rows=await self.get_price_history(listing_id); return rows[-2]["price"] if len(rows)>1 else None
    async def update_listing_analysis(self,listing_id:int,device_info:DeviceInfo,analysis:AIAnalysis,evaluation:FlipEvaluation)->None:
        c=self._require_connection(); await c.execute("UPDATE listings SET device_info=?,analysis_json=?,evaluation_json=?,flip_score=?,is_flip=? WHERE id=?",(_model_to_json(device_info),_model_to_json(analysis),_model_to_json(evaluation),evaluation.flip_score,int(evaluation.is_flip_candidate),listing_id)); await c.commit()
    async def mark_sent(self,listing_id:int)->None:
        c=self._require_connection(); await c.execute("UPDATE listings SET is_sent=1,sent_at=? WHERE id=?",(_utc_now_iso(),listing_id)); await c.commit()
    async def get_unsent_flips(self,limit:int=100)->list[dict]: return [dict(r) for r in await (await self._require_connection().execute("SELECT * FROM listings WHERE is_flip=1 AND is_sent=0 ORDER BY flip_score DESC,first_seen_at ASC LIMIT ?",(limit,))).fetchall()]
    async def mark_inactive_before(self,cutoff:datetime)->int:
        c=self._require_connection(); cur=await c.execute("UPDATE listings SET is_active=0 WHERE last_seen_at < ?",(cutoff.astimezone(timezone.utc).isoformat(),)); await c.commit(); return cur.rowcount
    async def upsert_market_listings(self,listings:list[Listing])->None:
        """Persist one current observation per external listing, retaining its latest price."""
        if not listings: return
        now=_utc_now_iso(); values=[]
        for listing in listings:
            key=market_key(listing)
            model,storage,condition,_ = key if key else (None,None,None,None)
            values.append((listing.source,listing.external_id,listing.url,listing.title,listing.price,listing.currency,model,storage,condition,listing.location,now,now))
        async with self._lock:
            await self._require_connection().executemany("INSERT INTO market_listings(source,external_id,url,title,price,currency,model,storage_gb,market_condition,location,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,external_id) DO UPDATE SET url=excluded.url,title=excluded.title,price=excluded.price,currency=excluded.currency,model=excluded.model,storage_gb=excluded.storage_gb,market_condition=excluded.market_condition,location=excluded.location,last_seen_at=excluded.last_seen_at,is_active=1",values)
            await self._require_connection().commit()
    async def get_market_universe(self,lookback_hours:int=72,now:datetime|None=None)->list[Listing]:
        if lookback_hours < 1: raise ValueError("lookback_hours must be >= 1")
        reference=(now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        cutoff=(reference-timedelta(hours=lookback_hours)).isoformat()
        rows=await (await self._require_connection().execute("SELECT source,external_id,url,title,price,currency,location,model,storage_gb,market_condition FROM market_listings WHERE is_active=1 AND last_seen_at >= ? ORDER BY last_seen_at DESC,id DESC",(cutoff,))).fetchall()
        states={"new":"new","good":"used","refurbished":"refurbished"}
        return [Listing(source=row["source"],external_id=str(row["external_id"]),url=row["url"] or "https://www.olx.pl/",title=row["title"],price=row["price"],currency=row["currency"],location=row["location"],attributes={key:value for key,value in {"phonemodel":row["model"],"builtinmemory_phones":f'{row["storage_gb"]}gb' if row["storage_gb"] else None,"state":states.get(row["market_condition"])}.items() if value is not None}) for row in rows]
    async def market_listing_count(self)->int:
        row=await (await self._require_connection().execute("SELECT COUNT(*) AS count FROM market_listings")).fetchone(); return int(row["count"])
    async def get_app_settings(self)->dict[str,Any]:
        rows=await (await self._require_connection().execute("SELECT key,value_json FROM app_settings")).fetchall()
        result={}
        for row in rows:
            try: result[row["key"]]=json.loads(row["value_json"])
            except json.JSONDecodeError: continue
        return result
    async def set_app_settings(self, values:dict[str,Any])->None:
        now=_utc_now_iso(); rows=[(key,_json_dumps(value),now) for key,value in values.items()]
        if not rows: return
        async with self._lock:
            await self._require_connection().executemany("INSERT INTO app_settings(key,value_json,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at",rows)
            await self._require_connection().commit()
    async def record_monitoring_run(self, started_at:str, finished_at:str, duration_seconds:float, stats:Any|None, status:str, error_message:str|None=None)->int:
        values=(started_at,finished_at,duration_seconds,getattr(stats,"unique",0),getattr(stats,"persistent_recent_rows",0),getattr(stats,"query_candidates",0),getattr(stats,"market_available",0),getattr(stats,"market_unavailable",0),getattr(stats,"analyzed",0),getattr(stats,"candidates",0),getattr(stats,"alerts_sent",0),getattr(stats,"errors",0),status,error_message)
        c=self._require_connection(); cur=await c.execute("INSERT INTO monitoring_runs(started_at,finished_at,duration_seconds,current_listings,persistent_market_rows,query_candidates,market_available,market_unavailable,ai_analysed,flip_candidates,alerts_sent,errors,status,error_message) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",values); await c.commit(); return int(cur.lastrowid)
    async def save_market_benchmark_snapshot(self, monitoring_run_id: int, captured_at: str, benchmarks: list[Any]) -> int:
        rows=[(monitoring_run_id,captured_at,item.model,item.storage_gb,item.condition,item.currency,item.sample_size,item.min_price,item.median_price,item.avg_price,item.max_price,"dynamic") for item in benchmarks if item.sample_size >= 3]
        if not rows: return 0
        c=self._require_connection(); before=c.total_changes; await c.executemany("INSERT OR IGNORE INTO market_benchmark_history(monitoring_run_id,captured_at,model,storage_gb,condition,currency,sample_size,min_price,median_price,avg_price,max_price,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",rows); await c.commit(); return c.total_changes - before
    async def get_market_benchmark_history(self, model: str, storage: int, condition: str, hours: int = 72) -> list[dict]:
        cutoff=(datetime.now(timezone.utc)-timedelta(hours=hours)).isoformat()
        rows=await (await self._require_connection().execute("SELECT captured_at,sample_size,min_price,median_price,avg_price,max_price FROM market_benchmark_history WHERE model=? AND storage_gb=? AND condition=? AND captured_at>=? ORDER BY captured_at ASC",(model,storage,condition,cutoff))).fetchall()
        return [dict(row) for row in rows]
    async def get_market_trends(self, limit: int = 4) -> list[dict]:
        rows=await (await self._require_connection().execute("SELECT h.* FROM market_benchmark_history h JOIN (SELECT model,storage_gb,condition,MAX(captured_at) latest FROM market_benchmark_history GROUP BY model,storage_gb,condition) x ON h.model=x.model AND h.storage_gb=x.storage_gb AND h.condition=x.condition AND h.captured_at=x.latest WHERE h.condition='good' ORDER BY h.sample_size DESC LIMIT ?",(limit,))).fetchall()
        result=[]
        for row in rows:
            prior=await (await self._require_connection().execute("SELECT * FROM market_benchmark_history WHERE model=? AND storage_gb=? AND condition=? AND captured_at<=? ORDER BY captured_at DESC LIMIT 1",(row["model"],row["storage_gb"],row["condition"],(datetime.fromisoformat(row["captured_at"])-timedelta(hours=20)).isoformat()))).fetchone()
            delta=(row["median_price"]-prior["median_price"]) if prior and prior["median_price"] else None
            result.append({"model":row["model"],"storage_gb":row["storage_gb"],"condition":row["condition"],"sample_size":row["sample_size"],"median_price":row["median_price"],"change_24h_pln":delta,"change_24h_pct":round(delta/prior["median_price"]*100,1) if delta is not None else None})
        return result
    async def list_monitoring_runs(self,limit:int=100)->list[dict]:
        rows=await (await self._require_connection().execute("SELECT * FROM monitoring_runs ORDER BY id DESC LIMIT ?",(limit,))).fetchall(); return [dict(row) for row in rows]
    async def admin_listings(self, kind:str="recent", limit:int=20)->list[dict]:
        if kind=="opportunities": where="is_flip=1"
        elif kind=="near_misses": where="is_flip=0 AND evaluation_json IS NOT NULL"
        else: where="analysis_json IS NOT NULL"
        rows=await (await self._require_connection().execute(f"SELECT * FROM listings WHERE {where} ORDER BY last_seen_at DESC LIMIT ?",(limit,))).fetchall()
        result=[]
        for raw in rows:
            row=dict(raw)
            try:
                analysis=json.loads(row.get("analysis_json") or "{}")
                evaluation=json.loads(row.get("evaluation_json") or "{}")
                attrs=json.loads(row.get("attributes_json") or "{}")
            except json.JSONDecodeError: continue
            if kind=="near_misses" and not (evaluation.get("flip_score",0)>=60 or evaluation.get("margin_pct",0)>=25): continue
            device=analysis.get("device_info") or {}
            result.append({"id":row["id"],"external_id":row["external_id"],"url":row["url"],"title":row["title"],"asking":row["price"],"location":row.get("location"),"last_seen_at":row["last_seen_at"],"is_sent":bool(row["is_sent"]),"sent_at":row.get("sent_at"),"is_active":bool(row["is_active"]),"review_status":row.get("review_status") or "new","review_note":row.get("review_note"),"reviewed_at":row.get("reviewed_at"),"favorite":bool(row.get("favorite")),"model":device.get("model"),"storage_gb":device.get("storage_gb"),"condition":device.get("condition"),"battery_health":device.get("battery_health"),"fraud_risk":analysis.get("fraud_risk"),"resale_confidence":evaluation.get("resale_confidence_used"),"summary":analysis.get("summary"),"red_flags":analysis.get("red_flags",[]),"positive_signals":analysis.get("positive_signals",[]),"device_info":device,"attributes":attrs,"evaluation":evaluation})
        return result
    async def admin_query_listings(self, kind: str = "opportunities", *, model: str | None = None,
        storage: int | None = None, city: str | None = None, review_status: str | None = None,
        risk: float | None = None, min_score: float | None = None, min_margin: float | None = None,
        sent: bool | None = None, active: bool | None = True, favorite: bool | None = None,
        sort: str = "newest", page: int = 1, page_size: int = 25) -> list[dict]:
        if kind == "opportunities": where = ["is_flip=1"]
        elif kind == "near_misses": where = ["is_flip=0", "evaluation_json IS NOT NULL"]
        else: where = ["analysis_json IS NOT NULL"]
        values: list[Any] = []
        if review_status: where.append("review_status=?"); values.append(review_status)
        if city: where.append("location LIKE ?"); values.append(f"%{city}%")
        if sent is not None: where.append("is_sent=?"); values.append(int(sent))
        if active is not None: where.append("is_active=?"); values.append(int(active))
        if favorite is not None: where.append("favorite=?"); values.append(int(favorite))
        order = {"newest": "last_seen_at DESC", "profit": "flip_score DESC", "margin": "flip_score DESC", "score": "flip_score DESC", "risk": "last_seen_at DESC", "asking": "price ASC"}.get(sort, "last_seen_at DESC")
        rows = await (await self._require_connection().execute(f"SELECT * FROM listings WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?", (*values, page_size, (page - 1) * page_size))).fetchall()
        result = self._admin_rows(rows, kind)
        def matches(row: dict) -> bool:
            evaluation = row["evaluation"]
            if kind == "near_misses" and not (evaluation.get("flip_score", 0) >= 60 or evaluation.get("margin_pct", 0) >= 25): return False
            if model and (row.get("model") or "").lower() != model.lower(): return False
            if storage is not None and row.get("storage_gb") != storage: return False
            if risk is not None and (row.get("fraud_risk") is None or row["fraud_risk"] > risk): return False
            if min_score is not None and evaluation.get("flip_score", 0) < min_score: return False
            if min_margin is not None and evaluation.get("margin_pct", 0) < min_margin: return False
            return True
        result = [row for row in result if matches(row)]
        if sort == "profit": result.sort(key=lambda row: row["evaluation"].get("estimated_profit") or 0, reverse=True)
        elif sort == "margin": result.sort(key=lambda row: row["evaluation"].get("margin_pct") or 0, reverse=True)
        elif sort == "score": result.sort(key=lambda row: row["evaluation"].get("flip_score") or 0, reverse=True)
        elif sort == "risk": result.sort(key=lambda row: row.get("fraud_risk") if row.get("fraud_risk") is not None else 1.0)
        return result
    def _admin_rows(self, rows: list[aiosqlite.Row], kind: str) -> list[dict]:
        result=[]
        for raw in rows:
            row=dict(raw)
            try: analysis=json.loads(row.get("analysis_json") or "{}"); evaluation=json.loads(row.get("evaluation_json") or "{}"); attrs=json.loads(row.get("attributes_json") or "{}")
            except json.JSONDecodeError: continue
            device=analysis.get("device_info") or {}
            result.append({"id":row["id"],"external_id":row["external_id"],"url":row["url"],"title":row["title"],"asking":row["price"],"location":row.get("location"),"last_seen_at":row["last_seen_at"],"is_sent":bool(row["is_sent"]),"sent_at":row.get("sent_at"),"is_active":bool(row["is_active"]),"review_status":row.get("review_status") or "new","review_note":row.get("review_note"),"reviewed_at":row.get("reviewed_at"),"favorite":bool(row.get("favorite")),"model":device.get("model"),"storage_gb":device.get("storage_gb"),"condition":device.get("condition"),"battery_health":device.get("battery_health"),"fraud_risk":analysis.get("fraud_risk"),"resale_confidence":evaluation.get("resale_confidence_used"),"summary":analysis.get("summary"),"red_flags":analysis.get("red_flags",[]),"positive_signals":analysis.get("positive_signals",[]),"device_info":device,"attributes":attrs,"evaluation":evaluation})
        return result
    async def update_listing_review(self, listing_id: int, review_status: str | None = None,
        review_note: str | None = None, favorite: bool | None = None) -> dict | None:
        updates: list[str] = []; values: list[Any] = []
        if review_status is not None: updates.extend(["review_status=?", "reviewed_at=?"]); values.extend([review_status, _utc_now_iso()])
        if review_note is not None: updates.extend(["review_note=?", "reviewed_at=?"]); values.extend([review_note, _utc_now_iso()])
        if favorite is not None: updates.append("favorite=?"); values.append(int(favorite))
        if not updates: return await self.get_listing(listing_id)
        c=self._require_connection(); await c.execute(f"UPDATE listings SET {','.join(updates)} WHERE id=?", (*values, listing_id)); await c.commit()
        return await self.get_listing(listing_id)
    async def admin_dashboard_counts(self)->dict[str,int]:
        c=self._require_connection()
        async def count(where:str)->int:
            row=await (await c.execute(f"SELECT COUNT(*) AS count FROM listings WHERE {where}")).fetchone(); return int(row["count"])
        return {"market_universe":await self.market_listing_count(),"opportunities":await count("is_flip=1"),"analysed":await count("analysis_json IS NOT NULL"),"sent":await count("is_sent=1"),"review_new":await count("review_status='new'"),"review_interesting":await count("review_status='interesting'"),"review_reviewing":await count("review_status='reviewing'")}
    async def get_listing(self,listing_id:int)->dict|None:
        r=await (await self._require_connection().execute("SELECT * FROM listings WHERE id=?",(listing_id,))).fetchone(); return dict(r) if r else None
    async def get_listing_by_external_id(self,source:str,external_id:str)->dict|None:
        r=await (await self._require_connection().execute("SELECT * FROM listings WHERE source=? AND external_id=?",(source,external_id))).fetchone(); return dict(r) if r else None
