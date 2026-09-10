"""One-shot translation of untrusted AI presentation text for Telegram alerts."""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from app.config import Settings

logger = logging.getLogger(__name__)
SYSTEM_PROMPT = (
    "You are a translation component. Translate the provided presentation text faithfully into the requested language. "
    "Do not analyze the listing, infer new facts, add or remove information, change risk severity, or merge or split facts unnecessarily. "
    "Do not modify numbers, currencies, product names, model names, storage values, or proper names. "
    "Preserve terms such as iPhone, Face ID, iCloud, SIM, IMEI, and PLN. Return strict JSON only."
)


class TranslatedNotificationContent(BaseModel):
    summary: str
    red_flags: list[str]
    positive_signals: list[str]


class NotificationTranslationError(RuntimeError):
    """A recoverable presentation-only translation failure."""


def translation_schema() -> dict[str, Any]:
    return {"type": "object", "properties": {"summary": {"type": "string"}, "red_flags": {"type": "array", "items": {"type": "string"}}, "positive_signals": {"type": "array", "items": {"type": "string"}}}, "required": ["summary", "red_flags", "positive_signals"], "additionalProperties": False}


class NotificationTranslator:
    """Translate only notification copy; it never changes canonical analysis data."""

    def __init__(self, settings: Settings, client: AsyncOpenAI | None = None) -> None:
        self._settings = settings
        self._client = client

    def _client_or_raise(self) -> AsyncOpenAI:
        if self._client is not None:
            return self._client
        if not self._settings.openai_api_key:
            raise NotificationTranslationError("translation is unavailable")
        self._client = AsyncOpenAI(api_key=self._settings.openai_api_key, base_url=self._settings.openai_base_url)
        return self._client

    def _request_kwargs(self, content: TranslatedNotificationContent, language: str) -> dict[str, Any]:
        target = "Russian" if language == "ru" else "Polish"
        payload = json.dumps(content.model_dump(), ensure_ascii=False)
        return {"model": self._settings.openai_model, "temperature": 0, "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": f"Target language: {target}\nTranslate this JSON:\n{payload}"}], "response_format": {"type": "json_schema", "json_schema": {"name": "translated_notification", "strict": True, "schema": translation_schema()}}}

    async def translate(self, target_language: str, summary: str, red_flags: list[str], positive_signals: list[str]) -> TranslatedNotificationContent:
        if target_language not in {"ru", "pl"}:
            raise NotificationTranslationError("unsupported target language")
        content = TranslatedNotificationContent(summary=summary, red_flags=list(red_flags), positive_signals=list(positive_signals))
        try:
            response = await self._client_or_raise().chat.completions.create(**self._request_kwargs(content, target_language))
            choices = getattr(response, "choices", None)
            raw = getattr(getattr(choices[0], "message", None), "content", None) if choices else None
            if not isinstance(raw, str) or not raw.strip():
                raise NotificationTranslationError("translation response has no content")
            return TranslatedNotificationContent.model_validate(json.loads(raw))
        except NotificationTranslationError:
            raise
        except (json.JSONDecodeError, ValidationError, TypeError) as exc:
            logger.warning("Notification translation response was invalid: %s", type(exc).__name__)
            raise NotificationTranslationError("translation response was invalid") from exc
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            logger.warning("Notification translation request failed%s", f" HTTP {status}" if status is not None else "")
            raise NotificationTranslationError("translation request failed") from exc

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close:
            await close()
