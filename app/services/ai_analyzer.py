"""OpenAI-compatible, single-call listing analysis."""
from __future__ import annotations

from copy import deepcopy
import json
import logging
import re
from typing import Any, Literal

from openai import AsyncOpenAI
from pydantic import ValidationError

from app.config import Settings
from app.exceptions import AIAnalysisError, ConfigurationError
from app.models import AIAnalysis, Listing, MarketPrice
from app.services.device_attributes import display_structured_attributes

logger = logging.getLogger(__name__)
MAX_DESCRIPTION_CHARS = 1500
MAX_REPAIR_CHARS = 4000
TEMPERATURE = 0.2
SYSTEM_PROMPT = """Ты — аналитик объявлений о подержанных iPhone на польском рынке. Извлекай только подтверждённые характеристики; неизвестное обозначай null. Ищи iCloud/операторские блокировки, повреждения, запчасти, IMEI/MDM и сигналы риска, но отсутствие информации не считай проблемой. Condition: new, excellent, good, fair, damaged или null. Оцени resale в PLN, confidence и технический fraud risk. Summary пиши по-русски, 1–3 предложения. Верни только JSON по заданной структуре."""
RequestMode = Literal["strict", "json_object", "plain"]


def _inline_refs(value: Any, definitions: dict[str, Any]) -> Any:
    if isinstance(value, list):
        return [_inline_refs(item, definitions) for item in value]
    if not isinstance(value, dict):
        return value
    if "$ref" in value:
        reference = value["$ref"].rsplit("/", 1)[-1]
        resolved = deepcopy(definitions[reference])
        resolved.update({key: item for key, item in value.items() if key != "$ref"})
        return _inline_refs(resolved, definitions)
    return {key: _inline_refs(item, definitions) for key, item in value.items()}


def _strictify_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_strictify_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {key: _strictify_schema(item) for key, item in value.items() if key not in {"title", "default"}}
    properties = result.get("properties")
    if isinstance(properties, dict):
        result["required"] = list(properties)
        result["additionalProperties"] = False
    # Groq documents nullable strict fields as type unions rather than anyOf.
    alternatives = result.get("anyOf")
    if isinstance(alternatives, list) and len(alternatives) == 2:
        types = [item.get("type") for item in alternatives if isinstance(item, dict) and set(item) <= {"type"}]
        if len(types) == 2 and "null" in types:
            return {key: item for key, item in result.items() if key != "anyOf"} | {"type": types}
    return result


def strict_ai_analysis_schema() -> dict[str, Any]:
    """Generate Groq-compatible strict JSON Schema from the Pydantic contract."""
    generated = AIAnalysis.model_json_schema()
    definitions = generated.pop("$defs", {})
    return _strictify_schema(_inline_refs(generated, definitions))


class AIAnalyzer:
    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None) -> None:
        if not settings.openai_api_key and client is None:
            raise ConfigurationError("OPENAI_API_KEY is required to use AIAnalyzer")
        self._settings = settings
        self._client = client or AsyncOpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close:
            await close()

    async def __aenter__(self) -> AIAnalyzer:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    def _uses_groq_strict(self) -> bool:
        return "api.groq.com" in self._settings.openai_base_url.casefold() and self._settings.openai_model == "qwen/qwen3.8-27b"

    def _build_user_prompt(self, listing: Listing, market: MarketPrice | None) -> str:
        desc = " ".join((listing.description or "").split())[:MAX_DESCRIPTION_CHARS]
        if market is None:
            market_text = "Market benchmark: unavailable"
        else:
            median = f"Median: {market.median_price} {market.currency}\n" if market.median_price is not None else ""
            market_text = (
                f"MARKET BENCHMARK\nModel: {market.model}\nStorage: {market.storage_gb}\nCondition: {market.condition}\n"
                f"Minimum: {market.min_price} {market.currency}\n{median}"
                f"Average: {market.avg_price} {market.currency}\nMaximum: {market.max_price} {market.currency}\n"
                f"Sample size: {market.sample_size}\nUpdated: {market.updated_at}\n"
                "This benchmark is based on current comparable OLX listings and excludes the current listing. "
                "Treat it as the primary pricing anchor: the asking price is not evidence of resale value. "
                "Condition, battery, and damage may adjust the estimate. Lower confidence for a small sample; "
                "do not copy the asking price automatically."
            )
        attributes = "\n".join(f"{label}: {value}" for label, value in display_structured_attributes(listing.attributes)) or "Unavailable"
        return f"LISTING\nTitle: {listing.title}\nAsking price: {listing.price} {listing.currency}\nLocation: {listing.location}\nSeller type: {listing.seller_type}\nPublished at: {listing.published_at}\nDescription:\n{desc}\n\nSTRUCTURED LISTING ATTRIBUTES\n{attributes}\nThese are seller-selected structured OLX attributes. Prefer them over inference from free text when present and internally consistent. If they conflict with title or description, mention the conflict as a red flag or uncertainty; do not silently overwrite it.\n\n{market_text}\n\nReturn object with device_info, estimated_resale_price, resale_confidence, recommended_buy_price, red_flags, positive_signals, fraud_risk, summary."

    @staticmethod
    def _strip_markdown_fences(raw: str) -> str:
        raw = raw.strip()
        match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw, re.S | re.I)
        return match.group(1).strip() if match else raw

    @staticmethod
    def _validation_diagnostic(error: Exception) -> str:
        if isinstance(error, ValidationError):
            return "; ".join(
                f"{'.'.join(str(part) for part in item['loc'])}: {item['msg'][:160]}"
                for item in error.errors()
            )[:1000]
        if isinstance(error, json.JSONDecodeError):
            return f"json_decode: {error.msg}"
        return type(error).__name__

    def _parse_response(self, raw: str) -> AIAnalysis:
        try:
            return AIAnalysis.model_validate(json.loads(self._strip_markdown_fences(raw)))
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            diagnostic = self._validation_diagnostic(exc)
            logger.warning("AIAnalysis response validation failed: %s", diagnostic)
            raise AIAnalysisError(f"LLM response is not valid AIAnalysis JSON: {diagnostic}") from exc

    @staticmethod
    def _unsupported_format(exc: Exception) -> bool:
        status = getattr(exc, "status_code", None)
        if status is not None and status not in {400, 404, 422}:
            return False
        text = str(exc).casefold()
        return "response_format" in text and any(token in text for token in ("unsupported", "not support", "invalid", "unknown"))

    @staticmethod
    def _request_error(exc: Exception) -> AIAnalysisError:
        status = getattr(exc, "status_code", None)
        suffix = f" (HTTP {status})" if status is not None else ""
        return AIAnalysisError(f"LLM request failed{suffix}")

    def _request_kwargs(self, messages: list[dict[str, str]], mode: RequestMode) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"model": self._settings.openai_model, "temperature": TEMPERATURE, "messages": messages}
        if mode == "strict":
            kwargs["response_format"] = {"type": "json_schema", "json_schema": {"name": "ai_analysis", "strict": True, "schema": strict_ai_analysis_schema()}}
            kwargs["reasoning_effort"] = "none"
        elif mode == "json_object":
            kwargs["response_format"] = {"type": "json_object"}
        return kwargs

    async def _request(self, messages: list[dict[str, str]], mode: RequestMode) -> tuple[str, RequestMode]:
        try:
            response = await self._client.chat.completions.create(**self._request_kwargs(messages, mode))
        except Exception as exc:
            if mode == "strict" and self._unsupported_format(exc):
                return await self._request(messages, "json_object")
            if mode == "json_object" and self._unsupported_format(exc):
                return await self._request(messages, "plain")
            raise self._request_error(exc) from exc
        choices = getattr(response, "choices", None)
        content = getattr(getattr(choices[0], "message", None), "content", None) if choices else None
        if not isinstance(content, str) or not content.strip():
            raise AIAnalysisError("LLM response has no content")
        return content, mode

    async def _repair_response(self, raw: str, error: Exception) -> AIAnalysis:
        prompt = f"Your previous response did not match the required JSON schema. Validation problem: {str(error)[:500]}. Return corrected JSON only. Previous response:\n{raw[:MAX_REPAIR_CHARS]}"
        repaired, _ = await self._request([{"role": "system", "content": "Return only valid JSON."}, {"role": "user", "content": prompt}], "json_object")
        return self._parse_response(repaired)

    async def analyze(self, listing: Listing, market: MarketPrice | None = None) -> AIAnalysis:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": self._build_user_prompt(listing, market)}]
        raw, mode = await self._request(messages, "strict" if self._uses_groq_strict() else "json_object")
        try:
            return self._parse_response(raw)
        except AIAnalysisError as exc:
            if mode == "strict":
                raise AIAnalysisError("Strict structured response failed AIAnalysis validation") from exc
            try:
                return await self._repair_response(raw, exc)
            except AIAnalysisError as repair:
                raise AIAnalysisError("LLM response remained invalid after one repair") from repair
