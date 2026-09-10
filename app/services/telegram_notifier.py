"""Telegram delivery for rendered flip alerts."""
from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from aiogram import Bot

from app.config import Settings
from app.exceptions import ConfigurationError
from app.models import AIAnalysis, FlipEvaluation, Listing
from app.services.notification_translator import NotificationTranslator, TranslatedNotificationContent
from app.services.telegram_renderer import TelegramRenderer
from app.storage.database import Database

logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Deliver one localized, escaped HTML alert per listing."""

    def __init__(
        self, settings: Settings, bot: Bot | None = None,
        language_loader: Callable[[], Awaitable[object]] | None = None,
        translator: NotificationTranslator | None = None,
    ) -> None:
        if not settings.telegram_chat_id:
            raise ConfigurationError("TELEGRAM_CHAT_ID is required to use TelegramNotifier")
        if bot is None:
            if not settings.telegram_bot_token:
                raise ConfigurationError("TELEGRAM_BOT_TOKEN is required to use TelegramNotifier")
            bot = Bot(token=settings.telegram_bot_token)
            self._owns_bot = True
        else:
            self._owns_bot = False
        self._bot = bot
        self._chat_id = settings.telegram_chat_id
        self._database_path = settings.database_path
        self._language_loader = language_loader or self._language_from_persistence
        self._translator = translator or NotificationTranslator(settings)
        self._closed = False

    async def _language_from_persistence(self) -> str:
        """Read the presentation preference at delivery time, with a safe fallback."""
        try:
            async with Database(self._database_path) as database:
                value = (await database.get_app_settings()).get("telegram_report_language")
        except Exception:
            logger.warning("Could not load Telegram report language; using Russian")
            return "ru"
        return TelegramRenderer.normalize_language(value)

    def format_message(
        self, listing: Listing, evaluation: FlipEvaluation, analysis: AIAnalysis,
        previous_price: int | None = None, language: object = "ru",
        translated_content: TranslatedNotificationContent | None = None,
    ) -> str:
        """Render a message without sending it; useful for previews and tests."""
        return TelegramRenderer.render(listing, analysis, evaluation, language, previous_price, translated_content)

    async def send_test_message(self):
        """Send one developer connectivity check without invoking the pipeline."""
        message = (
            "✅ <b>iPhone Flip Finder</b>\n\n"
            "Telegram integration работает.\n\n"
            "Это тестовое сообщение.\n"
            "OLX и AI в этом режиме не запускались."
        )
        result = await self._bot.send_message(
            chat_id=self._chat_id, text=message, parse_mode="HTML", disable_web_page_preview=True,
        )
        logger.info("Telegram test message sent")
        return result

    async def send_alert(
        self, listing: Listing, evaluation: FlipEvaluation, analysis: AIAnalysis,
        previous_price: int | None = None,
    ) -> None:
        language = TelegramRenderer.normalize_language(await self._language_loader())
        translated: TranslatedNotificationContent | None = None
        if evaluation.is_flip_candidate and any((analysis.summary, analysis.red_flags, analysis.positive_signals)):
            try:
                translated = await self._translator.translate(language, analysis.summary, analysis.red_flags, analysis.positive_signals)
            except Exception:
                logger.warning("Notification translation failed; using canonical text")
        message = self.format_message(listing, evaluation, analysis, previous_price, language, translated)
        await self._bot.send_message(
            chat_id=self._chat_id, text=message, parse_mode="HTML", disable_web_page_preview=False,
        )
        logger.info("Telegram alert sent for %s:%s", listing.source, listing.external_id)

    async def close(self) -> None:
        if self._owns_bot and not self._closed:
            await self._bot.session.close()
            self._closed = True
        close_translator = getattr(self._translator, "close", None)
        if close_translator:
            await close_translator()

    async def __aenter__(self) -> TelegramNotifier:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()
