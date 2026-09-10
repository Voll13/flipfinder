from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.exceptions import ConfigurationError
from app.models import AIAnalysis, DeviceInfo, FlipEvaluation, Listing
from app.services.telegram_notifier import TelegramNotifier
from app.services.telegram_renderer import TelegramRenderer
from app.storage.database import Database


def settings(**kwargs):
    return Settings(_env_file=None, telegram_chat_id="123", **kwargs)


def fake_bot():
    return SimpleNamespace(send_message=AsyncMock(), session=SimpleNamespace(close=AsyncMock()))


def samples(**listing_changes):
    listing_data = {"source": "olx", "external_id": "42", "url": 'https://www.olx.pl/d/oferta/42?q="<tag>', "title": " Piękny Apple iPhone 16e 128GB ", "price": 1797, "currency": "PLN", "location": "Kraków, Małopolskie", "seller_type": "business"}
    listing_data.update(listing_changes)
    listing = Listing(**listing_data)
    analysis = AIAnalysis(device_info=DeviceInfo(model="iPhone 16e", storage_gb=128, battery_health=100, condition="excellent", color="Blue", has_box=True, has_receipt=True, has_warranty=True), estimated_resale_price=2614, resale_confidence=.8, recommended_buy_price=1750, red_flags=["AI red flag"], positive_signals=["Original receipt"], fraud_risk=.1, summary="Clean <safe> device")
    evaluation = FlipEvaluation(flip_score=78.8, estimated_profit=817, margin_pct=45.5, fees_estimate=100, resale_price_used=2614, resale_source="dynamic_market", is_flip_candidate=True, reasons=["Healthy battery"])
    return listing, evaluation, analysis


def test_ru_renderer_has_fixed_labels_and_preserves_original_title():
    listing, evaluation, analysis = samples()
    message = TelegramRenderer.render(listing, analysis, evaluation, "ru")
    for expected in ("🔥 <b>Выгодный iPhone</b>", "📍 Локация:", "👤 Продавец: Бизнес", "📈 Оценка перепродажи:", "📉 Основа оценки: рынок OLX", "✅ Рекомендуемая цена покупки:", "📱 iPhone 16e · 128 GB · Отличное", "🔋 Батарея: 100%", "📦 Комплект: коробка, чек, гарантия", "⚠️ <b>Риски:</b>", "👍 <b>Плюсы:</b>", "📝 <b>Анализ:</b>", "Открыть объявление на OLX", "Piękny Apple iPhone 16e 128GB"):
        assert expected in message


def test_pl_renderer_has_fixed_labels_and_preserves_original_title():
    listing, evaluation, analysis = samples()
    message = TelegramRenderer.render(listing, analysis, evaluation, "pl")
    for expected in ("🔥 <b>Okazja iPhone</b>", "📍 Lokalizacja:", "👤 Sprzedawca: Firma", "📈 Szacowana cena odsprzedaży:", "📉 Podstawa wyceny: rynek OLX", "📱 iPhone 16e · 128 GB · Doskonały", "🔋 Bateria: 100%", "📦 Zestaw: pudełko, dowód zakupu, gwarancja", "⚠️ <b>Ryzyka:</b>", "👍 <b>Zalety:</b>", "📝 <b>Analiza:</b>", "Otwórz ogłoszenie na OLX", "Piękny Apple iPhone 16e 128GB"):
        assert expected in message


def test_renderer_formats_numeric_values_and_maps_seller_condition_package_and_market():
    listing, evaluation, analysis = samples(seller_type="private")
    ru = TelegramRenderer.render(listing, analysis, evaluation, "ru")
    pl = TelegramRenderer.render(listing, analysis, evaluation, "pl")
    for message in (ru, pl):
        assert "1 797 PLN" in message and "2 614 PLN" in message and "+817 PLN" in message
        assert "45,5%" in message and "78,8 / 100" in message
    assert "Частное лицо" in ru and "Отличное" in ru and "рынок OLX" in ru
    assert "Osoba prywatna" in pl and "Doskonały" in pl and "rynek OLX" in pl
    assert TelegramRenderer.boolean(True, "ru") == "Да"
    assert TelegramRenderer.boolean(False, "pl") == "Nie"
    assert TelegramRenderer.boolean(None, "ru") == "Неизвестно"


@pytest.mark.parametrize(("language", "headline", "drop", "old", "new", "decrease", "profit", "margin"), [
    ("ru", "Выгодный iPhone", "Цена снижена", "Старая цена", "Новая цена", "Снижение", "Новая прибыль", "Новая маржа"),
    ("pl", "Okazja iPhone", "Obniżka ceny", "Poprzednia cena", "Nowa cena", "Spadek", "Nowy zysk", "Nowa marża"),
])
def test_price_drop_uses_localized_fixed_labels(language, headline, drop, old, new, decrease, profit, margin):
    listing, evaluation, analysis = samples()
    message = TelegramRenderer.render(listing, analysis, evaluation, language, previous_price=2000)
    for expected in (headline, drop, old, new, decrease, profit, margin):
        assert expected in message
    assert "203 PLN" in message


def test_renderer_escapes_html_and_does_not_change_scoring_or_inputs():
    listing, evaluation, analysis = samples(title="<b>source</b>", location="<city>")
    before = (listing.model_dump(), analysis.model_dump(), evaluation.model_dump())
    message = TelegramRenderer.render(listing, analysis, evaluation, "pl")
    assert "&lt;b&gt;source&lt;/b&gt;" in message and "&lt;safe&gt;" in message and "<safe>" not in message
    assert 'href="https://www.olx.pl/d/oferta/42?q=&quot;&lt;tag&gt;"' in message
    assert before == (listing.model_dump(), analysis.model_dump(), evaluation.model_dump())
    assert evaluation.is_flip_candidate is True and evaluation.flip_score == 78.8


@pytest.mark.asyncio
@pytest.mark.parametrize(("language", "expected"), [("ru", "Выгодный iPhone"), ("pl", "Okazja iPhone"), ("invalid", "Выгодный iPhone"), (None, "Выгодный iPhone")])
async def test_notifier_selects_renderer_language_with_safe_fallback(language, expected):
    listing, evaluation, analysis = samples()
    bot = fake_bot()
    async def load_language(): return language
    await TelegramNotifier(settings(), bot, load_language).send_alert(listing, evaluation, analysis)
    assert expected in bot.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_notifier_reads_persisted_telegram_report_language_before_send(tmp_path):
    db_path = str(tmp_path / "settings.db")
    async with Database(db_path) as database:
        await database.set_app_settings({"telegram_report_language": "pl"})
    listing, evaluation, analysis = samples()
    bot = fake_bot()
    await TelegramNotifier(settings(database_path=db_path), bot).send_alert(listing, evaluation, analysis)
    assert "Okazja iPhone" in bot.send_message.await_args.kwargs["text"]


@pytest.mark.asyncio
async def test_send_alert_uses_injected_bot_and_propagates_errors():
    listing, evaluation, analysis = samples()
    bot = fake_bot()
    async def ru(): return "ru"
    notifier = TelegramNotifier(settings(), bot, ru)
    await notifier.send_alert(listing, evaluation, analysis)
    bot.send_message.assert_awaited_once()
    assert bot.send_message.await_args.kwargs["chat_id"] == "123"
    assert bot.send_message.await_args.kwargs["parse_mode"] == "HTML"
    bot.send_message.side_effect = RuntimeError("telegram unavailable")
    with pytest.raises(RuntimeError, match="telegram unavailable"):
        await notifier.send_alert(listing, evaluation, analysis)


@pytest.mark.asyncio
async def test_test_message_sends_once_and_closes_owned_session(monkeypatch):
    bot = fake_bot(); bot.send_message.return_value = SimpleNamespace(message_id=42)
    monkeypatch.setattr("app.services.telegram_notifier.Bot", lambda token: bot)
    async with TelegramNotifier(settings(telegram_bot_token="token")) as notifier:
        result = await notifier.send_test_message()
    assert result.message_id == 42 and bot.send_message.await_count == 1
    bot.session.close.assert_awaited_once()


def test_configuration_requirements_and_injected_bot_without_token():
    with pytest.raises(ConfigurationError, match="TELEGRAM_BOT_TOKEN"):
        TelegramNotifier(Settings(_env_file=None, telegram_chat_id="123"))
    with pytest.raises(ConfigurationError, match="TELEGRAM_CHAT_ID"):
        TelegramNotifier(Settings(_env_file=None, telegram_bot_token="token"), fake_bot())
    TelegramNotifier(settings(), fake_bot())


@pytest.mark.asyncio
async def test_close_only_closes_owned_bot_and_context_manager(monkeypatch):
    injected = fake_bot(); await TelegramNotifier(settings(), injected).close(); injected.session.close.assert_not_awaited()
    owned = fake_bot(); monkeypatch.setattr("app.services.telegram_notifier.Bot", lambda token: owned)
    async with TelegramNotifier(settings(telegram_bot_token="token")):
        pass
    owned.session.close.assert_awaited_once()
