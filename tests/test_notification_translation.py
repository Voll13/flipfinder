from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.models import AIAnalysis, DeviceInfo, FlipEvaluation, Listing
from app.services.notification_translator import NotificationTranslationError, NotificationTranslator, TranslatedNotificationContent
from app.services.telegram_notifier import TelegramNotifier


def sample():
    listing = Listing(source="olx", external_id="1", url="https://olx.test/iPhone", title="Piękny iPhone 16 Pro 128GB", price=1797, location="Kraków", seller_type="private")
    analysis = AIAnalysis(device_info=DeviceInfo(model="iPhone 16 Pro", storage_gb=128, condition="excellent"), estimated_resale_price=2614, resale_confidence=.8, fraud_risk=.1, red_flags=["Model mismatch"], positive_signals=["Face ID, iCloud, SIM and IMEI verified"], summary="Battery condition is 100% at 2 614 PLN.")
    evaluation = FlipEvaluation(flip_score=78.8, estimated_profit=817, margin_pct=45.5, resale_price_used=2614, resale_source="dynamic_market", is_flip_candidate=True)
    return listing, analysis, evaluation


def bot():
    return SimpleNamespace(send_message=AsyncMock(), session=SimpleNamespace(close=AsyncMock()))


class Translator:
    def __init__(self, result=None, error=None):
        self.translate = AsyncMock(return_value=result)
        if error:
            self.translate.side_effect = error
    async def close(self): pass


async def language(value): return value


@pytest.mark.asyncio
@pytest.mark.parametrize(("target", "heading", "summary"), [
    ("ru", "Выгодный iPhone", "Батарея имеет состояние 100% при 2 614 PLN."),
    ("pl", "Okazja iPhone", "Kondycja baterii wynosi 100% przy 2 614 PLN."),
])
async def test_candidate_alert_translates_once_and_renderer_uses_content(target, heading, summary):
    listing, analysis, evaluation = sample()
    translated = TranslatedNotificationContent(summary=summary, red_flags=["Rozbieżność modelu"], positive_signals=["Face ID i iCloud zweryfikowane"])
    service, telegram = Translator(translated), bot()
    notifier = TelegramNotifier(Settings(_env_file=None, telegram_chat_id="1"), telegram, lambda: language(target), service)
    await notifier.send_alert(listing, evaluation, analysis)
    service.translate.assert_awaited_once_with(target, analysis.summary, analysis.red_flags, analysis.positive_signals)
    message = telegram.send_message.await_args.kwargs["text"]
    assert heading in message and summary in message and "Rozbieżność modelu" in message
    assert listing.title in message


@pytest.mark.asyncio
async def test_non_candidate_never_translates_and_scoring_remains_unchanged():
    listing, analysis, evaluation = sample()
    evaluation.is_flip_candidate = False
    before = evaluation.model_dump()
    service, telegram = Translator(TranslatedNotificationContent(summary="translated", red_flags=[], positive_signals=[])), bot()
    await TelegramNotifier(Settings(_env_file=None, telegram_chat_id="1"), telegram, lambda: language("ru"), service).send_alert(listing, evaluation, analysis)
    service.translate.assert_not_awaited()
    assert evaluation.model_dump() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [NotificationTranslationError("HTTP 429"), TimeoutError(), NotificationTranslationError("invalid JSON")])
async def test_translation_failures_fall_back_and_alert_still_sends(error, caplog):
    listing, analysis, evaluation = sample()
    service, telegram = Translator(error=error), bot()
    await TelegramNotifier(Settings(_env_file=None, telegram_chat_id="1"), telegram, lambda: language("ru"), service).send_alert(listing, evaluation, analysis)
    message = telegram.send_message.await_args.kwargs["text"]
    assert analysis.summary in message and analysis.red_flags[0] in message
    assert "Notification translation failed; using canonical text" in caplog.text


@pytest.mark.asyncio
async def test_translated_text_is_html_escaped_and_preserves_source_terms():
    listing, analysis, evaluation = sample()
    translated = TranslatedNotificationContent(summary="<safe> Face ID iCloud SIM IMEI 2 614 PLN", red_flags=["<risk>"], positive_signals=["Face ID"])
    service, telegram = Translator(translated), bot()
    await TelegramNotifier(Settings(_env_file=None, telegram_chat_id="1"), telegram, lambda: language("pl"), service).send_alert(listing, evaluation, analysis)
    message = telegram.send_message.await_args.kwargs["text"]
    assert "&lt;safe&gt;" in message and "&lt;risk&gt;" in message and "<safe>" not in message
    for term in ("Face ID", "iCloud", "SIM", "IMEI", "2 614 PLN", listing.title):
        assert term in message


@pytest.mark.asyncio
async def test_price_drop_without_ai_text_does_not_call_translator():
    listing, analysis, evaluation = sample()
    analysis.summary = ""; analysis.red_flags = []; analysis.positive_signals = []
    service, telegram = Translator(TranslatedNotificationContent(summary="x", red_flags=[], positive_signals=[])), bot()
    await TelegramNotifier(Settings(_env_file=None, telegram_chat_id="1"), telegram, lambda: language("pl"), service).send_alert(listing, evaluation, analysis, previous_price=2000)
    service.translate.assert_not_awaited()
    assert "Obniżka ceny" in telegram.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_translator_parses_strict_json_without_mutating_source():
    content = '{"summary":"Русский текст","red_flags":["Риск"],"positive_signals":["Плюс"]}'
    create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))]))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    source = {"summary": "English", "red_flags": ["Risk"], "positive_signals": ["Signal"]}
    result = await NotificationTranslator(Settings(_env_file=None), client).translate("ru", **source)
    assert result.summary == "Русский текст" and source["summary"] == "English"
    assert create.await_count == 1 and create.await_args.kwargs["response_format"]["type"] == "json_schema"
