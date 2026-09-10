"""Small local market-price lookup service."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.models import DeviceInfo, Listing, MarketPrice

logger = logging.getLogger(__name__)
_MODEL_RE = re.compile(r"\biphone\s+(1[1-6])(?:\s+(pro\s+max|mini|plus|pro))?\b", re.I)
_STORAGE_RE = re.compile(r"\b(64|128|256|512|1|2)\s*(gb|tb)\b", re.I)
_CONDITION_ALIASES = {"very good": "excellent", "very_good": "excellent", "used good": "good", "used_good": "good", "used": "good"}
_FALLBACKS = {"excellent": ("good",), "new": ("excellent", "good"), "fair": ("good",), "used": ("good",)}

def _normalize(value: str) -> str: return " ".join(value.strip().casefold().split())
def _normalize_model(value: str) -> str: return _normalize(value)
def _normalize_condition(value: str) -> str:
    value = _normalize(value).replace("_", " ")
    return _CONDITION_ALIASES.get(value, value)

class MarketDataProvider:
    def __init__(self, path: str) -> None: self.path=Path(path); self._index:dict[tuple[str,int,str],MarketPrice]={}
    async def load(self) -> None:
        if not self.path.exists(): logger.warning("Market price file is missing: %s",self.path); self._index={}; return
        try: raw=json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc: raise ValueError("Market price JSON is malformed") from exc
        if not isinstance(raw,list): raise ValueError("Market price JSON top level must be a list")
        index={}
        for item in raw:
            market=MarketPrice.model_validate(item)
            key=(_normalize_model(market.model),market.storage_gb,_normalize_condition(market.condition))
            if key in index: raise ValueError(f"Duplicate market price entry: {key}")
            index[key]=market
        self._index=index; logger.info("Loaded %d market price entries",len(index))
    def lookup(self,model:str,storage_gb:int,condition:str)->MarketPrice|None:
        result=self._index.get((_normalize_model(model),storage_gb,_normalize_condition(condition)))
        if result is None: logger.debug("Market lookup miss: %s/%s/%s",model,storage_gb,condition)
        return result
    def extract_device_hint(self,title:str)->tuple[str|None,int|None]:
        model_match=_MODEL_RE.search(title); storage_match=_STORAGE_RE.search(title)
        model=None
        if model_match:
            suffix=(model_match.group(2) or "").title(); model=f"iPhone {model_match.group(1)}"+(f" {suffix}" if suffix else "")
        storage=None
        if storage_match:
            storage=int(storage_match.group(1))*(1024 if storage_match.group(2).casefold()=="tb" else 1)
        return model,storage
    def lookup_for_listing(self,listing:Listing)->MarketPrice|None:
        model,storage=self.extract_device_hint(listing.title)
        return self.lookup(model,storage,"good") if model and storage else None
    def lookup_for_device(self,device:DeviceInfo)->MarketPrice|None:
        if not device.model or not device.storage_gb: return None
        condition=_normalize_condition(device.condition or "good")
        return self.lookup(device.model,device.storage_gb,condition) or (None if condition in {"damaged","locked"} else next((found for fallback in _FALLBACKS.get(condition,()) if (found:=self.lookup(device.model,device.storage_gb,fallback))),None))
