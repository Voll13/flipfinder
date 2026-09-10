from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.exceptions import AIAnalysisError, ConfigurationError
from app.models import Listing, MarketPrice
from app.services.ai_analyzer import AIAnalyzer, MAX_DESCRIPTION_CHARS, strict_ai_analysis_schema


def payload(**overrides):
    result = {"device_info": {"model": "iPhone 15 Pro", "storage_gb": 256, "battery_health": 91, "condition": "good", "color": None, "has_box": None, "has_receipt": None, "has_warranty": None, "damaged": False, "screen_damaged": False, "icloud_locked": False, "operator_locked": False, "sim_type": None}, "estimated_resale_price": 3000, "resale_confidence": .8, "recommended_buy_price": 2400, "red_flags": [], "positive_signals": [], "fraud_risk": .1, "summary": "Кратко."}
    result.update(overrides)
    return json.dumps(result)


def fake(contents):
    create = AsyncMock(side_effect=[item if isinstance(item, (Exception, SimpleNamespace)) else SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=item))]) for item in contents])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)), close=AsyncMock()), create


def listing(desc=None):
    return Listing(source="olx", external_id="1", url="https://x", title="iPhone 15 Pro 256GB", price=2000, description=desc)


def groq_settings():
    return Settings(_env_file=None, openai_api_key="test", openai_base_url="https://api.groq.com/openai/v1", openai_model="qwen/qwen3.8-27b")


class RequestError(Exception):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


@pytest.mark.asyncio
async def test_non_groq_keeps_json_object_request_and_prompt():
    client, create = fake([payload()])
    analyzer = AIAnalyzer(Settings(_env_file=None), client)
    item = listing("x " * 2000)
    analysis = await analyzer.analyze(item)
    assert analysis.device_info.model == "iPhone 15 Pro" and create.call_count == 1
    kwargs = create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-mini" and kwargs["response_format"] == {"type": "json_object"}
    assert "reasoning_effort" not in kwargs
    assert "Market benchmark: unavailable" in kwargs["messages"][1]["content"] and len(item.description) > MAX_DESCRIPTION_CHARS


def test_prompt_includes_canonical_structured_attributes_without_mutating_description():
    analyzer = AIAnalyzer(Settings(_env_file=None), fake([])[0])
    item = listing("Original description")
    item.attributes = {"phonemodel": "iphone-15-pro", "builtinmemory_phones": "128gb", "state": "used", "coloriphone": "silver"}
    prompt = analyzer._build_user_prompt(item, None)
    assert "Model: iPhone 15 Pro" in prompt and "Storage: 128 GB" in prompt and "Color: silver" in prompt
    assert "seller-selected structured OLX attributes" in prompt and "conflict" in prompt
    assert item.description == "Original description"


def test_prompt_explains_dynamic_market_anchor_and_small_sample():
    analyzer = AIAnalyzer(Settings(_env_file=None), fake([])[0])
    market = MarketPrice(model="iPhone 15 Pro", storage_gb=128, condition="good", min_price=2300, avg_price=2500, max_price=2600, sample_size=3)
    prompt = analyzer._build_user_prompt(listing(), market)
    assert "excludes the current listing" in prompt and "asking price is not evidence" in prompt and "small sample" in prompt


def test_groq_strict_schema_is_complete_and_nullable():
    schema = strict_ai_analysis_schema()
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False
    device = schema["properties"]["device_info"]
    assert set(device["required"]) == set(device["properties"])
    assert device["additionalProperties"] is False
    assert set(device["properties"]["battery_health"]["type"]) == {"integer", "null"}
    assert set(schema["properties"]["recommended_buy_price"]["type"]) == {"integer", "null"}


@pytest.mark.asyncio
async def test_groq_uses_strict_schema_and_valid_response_needs_one_request():
    client, create = fake([payload()])
    analysis = await AIAnalyzer(groq_settings(), client).analyze(listing())
    kwargs = create.call_args.kwargs
    assert analysis.estimated_resale_price == 3000 and create.call_count == 1
    assert kwargs["response_format"]["type"] == "json_schema"
    assert kwargs["response_format"]["json_schema"]["strict"] is True
    assert kwargs["reasoning_effort"] == "none"


@pytest.mark.asyncio
async def test_strict_schema_rejection_falls_back_to_json_object():
    client, create = fake([RequestError("response_format json_schema unsupported", 400), payload()])
    assert (await AIAnalyzer(groq_settings(), client).analyze(listing())).summary == "Кратко."
    assert create.call_count == 2
    assert create.call_args_list[0].kwargs["response_format"]["type"] == "json_schema"
    assert create.call_args_list[1].kwargs["response_format"] == {"type": "json_object"}


@pytest.mark.asyncio
async def test_429_never_falls_back_or_repairs():
    client, create = fake([RequestError("rate limited", 429)])
    with pytest.raises(AIAnalysisError, match="HTTP 429"):
        await AIAnalyzer(groq_settings(), client).analyze(listing())
    assert create.call_count == 1


@pytest.mark.asyncio
async def test_non_strict_provider_still_repairs_invalid_json():
    client, create = fake(["not json", payload()])
    assert (await AIAnalyzer(Settings(_env_file=None), client).analyze(listing())).summary == "Кратко."
    assert create.call_count == 2


def test_sanitized_validation_diagnostics_exclude_raw_response_and_key(caplog):
    client, _ = fake([])
    analyzer = AIAnalyzer(Settings(_env_file=None), client)
    raw = '{"fraud_risk": 2, "summary": "SECRET_RESPONSE"}'
    with pytest.raises(AIAnalysisError, match="fraud_risk"):
        analyzer._parse_response(raw)
    assert "SECRET_RESPONSE" not in caplog.text and "test-api-key" not in caplog.text
    assert "fraud_risk" in caplog.text


def test_parse_fences_and_errors():
    client, _ = fake([])
    analyzer = AIAnalyzer(Settings(_env_file=None), client)
    assert analyzer._parse_response("```json\n" + payload() + "\n```").fraud_risk == .1
    with pytest.raises(AIAnalysisError):
        analyzer._parse_response("bad")


@pytest.mark.asyncio
async def test_empty_lifecycle_and_missing_key():
    client, _ = fake([SimpleNamespace(choices=[])])
    analyzer = AIAnalyzer(Settings(_env_file=None), client)
    with pytest.raises(AIAnalysisError):
        await analyzer.analyze(listing())
    await analyzer.close()
    await analyzer.close()
    assert client.close.call_count == 2
    with pytest.raises(ConfigurationError):
        AIAnalyzer(Settings(_env_file=None))
