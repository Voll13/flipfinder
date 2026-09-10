"""Print recent private Telegram chat IDs without exposing the bot token."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Direct ``python scripts/...`` execution starts with scripts/ on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiogram import Bot

from app.config import Settings
from app.exceptions import ConfigurationError


def _chat_from_update(update):
    for message in (update.message, update.edited_message, update.channel_post):
        if message is not None and message.chat.type == "private":
            return message.chat
    return None


async def main() -> None:
    settings = Settings()
    if not settings.telegram_bot_token:
        raise ConfigurationError("TELEGRAM_BOT_TOKEN is required")
    bot = Bot(token=settings.telegram_bot_token)
    try:
        updates = await bot.get_updates()
        chats = []
        seen = set()
        for update in reversed(updates):
            chat = _chat_from_update(update)
            if chat is not None and chat.id not in seen:
                seen.add(chat.id)
                chats.append(chat)
        if not chats:
            print("No private updates found. Send /start to the bot and run this utility again.")
            return
        for chat in chats:
            name = chat.username or " ".join(part for part in (chat.first_name, chat.last_name) if part) or "unavailable"
            print(f"chat_id: {chat.id}")
            print(f"chat type: {chat.type}")
            print(f"name: {name}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
