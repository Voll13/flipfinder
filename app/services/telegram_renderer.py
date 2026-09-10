"""Localized presentation for Telegram flip alerts."""
from __future__ import annotations

from html import escape

from app.models import AIAnalysis, FlipEvaluation, Listing
from app.services.notification_translator import TranslatedNotificationContent


class TelegramRenderer:
    """Render escaped, fixed-label Telegram HTML without changing domain data."""

    MAX_MESSAGE_LENGTH = 4000

    _TEXT = {
        "ru": {
            "headline": "Выгодный iPhone", "location": "Локация", "seller": "Продавец",
            "price": "Цена", "resale": "Оценка перепродажи", "profit": "Ожидаемая прибыль",
            "margin": "Маржа", "score": "Рейтинг", "basis": "Основа оценки",
            "buy": "Рекомендуемая цена покупки", "battery": "Батарея", "package": "Комплект",
            "risks": "Риски", "positives": "Плюсы", "analysis": "Анализ",
            "open": "Открыть объявление на OLX", "unknown": "Неизвестно",
            "condition_unknown": "Не определено", "market": "рынок OLX",
            "price_drop": "Цена снижена", "old_price": "Старая цена", "new_price": "Новая цена",
            "decrease": "Снижение", "new_profit": "Новая прибыль", "new_margin": "Новая маржа",
            "seller_values": {"private": "Частное лицо", "business": "Бизнес"},
            "condition_values": {"new": "Новый", "excellent": "Отличное", "good": "Хорошее", "fair": "Удовлетворительное", "damaged": "Повреждённое"},
            "package_values": {"box": "коробка", "receipt": "чек", "warranty": "гарантия"},
        },
        "pl": {
            "headline": "Okazja iPhone", "location": "Lokalizacja", "seller": "Sprzedawca",
            "price": "Cena", "resale": "Szacowana cena odsprzedaży", "profit": "Oczekiwany zysk",
            "margin": "Marża", "score": "Ocena", "basis": "Podstawa wyceny",
            "buy": "Rekomendowana cena zakupu", "battery": "Bateria", "package": "Zestaw",
            "risks": "Ryzyka", "positives": "Zalety", "analysis": "Analiza",
            "open": "Otwórz ogłoszenie na OLX", "unknown": "Nieznane",
            "condition_unknown": "Nieokreślony", "market": "rynek OLX",
            "price_drop": "Obniżka ceny", "old_price": "Poprzednia cena", "new_price": "Nowa cena",
            "decrease": "Spadek", "new_profit": "Nowy zysk", "new_margin": "Nowa marża",
            "seller_values": {"private": "Osoba prywatna", "business": "Firma"},
            "condition_values": {"new": "Nowy", "excellent": "Doskonały", "good": "Dobry", "fair": "Dostateczny", "damaged": "Uszkodzony"},
            "package_values": {"box": "pudełko", "receipt": "dowód zakupu", "warranty": "gwarancja"},
        },
    }

    @classmethod
    def normalize_language(cls, language: object) -> str:
        return str(language).casefold() if str(language).casefold() in cls._TEXT else "ru"

    @staticmethod
    def format_money(value: int | float, currency: str = "PLN", signed: bool = False) -> str:
        amount = int(round(float(value)))
        prefix = "+" if signed and amount > 0 else ""
        return f"{prefix}{amount:,}".replace(",", " ") + f" {currency}"

    @staticmethod
    def format_number(value: int | float) -> str:
        number = float(value)
        text = f"{number:.1f}".rstrip("0").rstrip(".")
        return text.replace(".", ",")

    @staticmethod
    def boolean(value: bool | None, language: object = "ru") -> str:
        lang = TelegramRenderer.normalize_language(language)
        return ({"ru": {True: "Да", False: "Нет", None: "Неизвестно"}, "pl": {True: "Tak", False: "Nie", None: "Nieznane"}}[lang])[value]

    @staticmethod
    def _short(value: object, limit: int) -> str:
        text = str(value or "").strip()
        if len(text) > limit:
            text = text[: limit - 1].rstrip() + "…"
        return escape(text, quote=True)

    @staticmethod
    def _unique(values: list[str], limit: int) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            clean = str(value).strip()
            if clean and clean.casefold() not in seen:
                seen.add(clean.casefold())
                result.append(clean)
                if len(result) == limit:
                    break
        return result

    @classmethod
    def _source(cls, source: str | None, language: str) -> str:
        if (source or "").casefold() in {"dynamic_market", "market", "olx_market", "persistent_market"}:
            return cls._TEXT[language]["market"]
        return cls._TEXT[language]["unknown"]

    @classmethod
    def render(
        cls, listing: Listing, analysis: AIAnalysis, evaluation: FlipEvaluation,
        language: object = "ru", previous_price: int | None = None,
        translated_content: TranslatedNotificationContent | None = None,
    ) -> str:
        lang = cls.normalize_language(language)
        text = cls._TEXT[lang]
        device = analysis.device_info
        seller = text["seller_values"].get((listing.seller_type or "").casefold(), text["unknown"])
        condition = text["condition_values"].get((device.condition or "").casefold(), text["condition_unknown"])
        resale = evaluation.resale_price_used if evaluation.resale_price_used is not None else analysis.estimated_resale_price
        lines = [
            f"🔥 <b>{text['headline']}</b>",
            f"<b>{cls._short(listing.title, 250)}</b>",
            f"📍 {text['location']}: {cls._short(listing.location, 160) if listing.location else text['unknown']}",
            f"👤 {text['seller']}: {seller}",
            "",
            f"💰 {text['price']}: <b>{cls.format_money(listing.price, listing.currency)}</b>",
            f"📈 {text['resale']}: {cls.format_money(resale, listing.currency)}",
            f"💵 {text['profit']}: <b>{cls.format_money(evaluation.estimated_profit, listing.currency, signed=True)}</b>",
            f"📊 {text['margin']}: {cls.format_number(evaluation.margin_pct)}%",
            f"⭐ {text['score']}: <b>{cls.format_number(evaluation.flip_score)} / 100</b>",
            "",
            f"📉 {text['basis']}: {cls._source(evaluation.resale_source, lang)}",
        ]
        if analysis.recommended_buy_price is not None:
            lines.append(f"✅ {text['buy']}: {cls.format_money(analysis.recommended_buy_price, listing.currency)}")

        device_parts = [part for part in (cls._short(device.model, 100) if device.model else None, f"{device.storage_gb} GB" if device.storage_gb is not None else None, condition, cls._short(device.color, 80) if device.color else None) if part]
        lines.extend(["", "📱 " + " · ".join(device_parts), f"🔋 {text['battery']}: {f'{device.battery_health}%' if device.battery_health is not None else text['unknown']}"])
        kit = [label for value, label in ((device.has_box, text['package_values']['box']), (device.has_receipt, text['package_values']['receipt']), (device.has_warranty, text['package_values']['warranty'])) if value is True]
        lines.append(f"📦 {text['package']}: {', '.join(kit) if kit else text['unknown']}")

        presentation = translated_content or TranslatedNotificationContent(summary=analysis.summary, red_flags=list(analysis.red_flags), positive_signals=list(analysis.positive_signals))
        risks = cls._unique(list(presentation.red_flags), 5)
        lines.extend(["", f"⚠️ <b>{text['risks']}:</b>"])
        lines.extend(f"• {cls._short(value, 180)}" for value in risks) if risks else lines.append(f"• {text['unknown']}")
        positives = cls._unique(list(presentation.positive_signals), 3)
        lines.extend(["", f"👍 <b>{text['positives']}:</b>"])
        lines.extend(f"• {cls._short(value, 180)}" for value in positives) if positives else lines.append(f"• {text['unknown']}")
        lines.extend(["", f"📝 <b>{text['analysis']}:</b>", cls._short(presentation.summary, 500) or text['unknown']])

        if previous_price is not None and listing.price < previous_price:
            decrease = previous_price - listing.price
            lines.extend(["", f"📉 <b>{text['price_drop']}</b>", f"{text['old_price']}: {cls.format_money(previous_price, listing.currency)}", f"{text['new_price']}: {cls.format_money(listing.price, listing.currency)}", f"{text['decrease']}: {cls.format_money(decrease, listing.currency)}", f"{text['new_profit']}: {cls.format_money(evaluation.estimated_profit, listing.currency, signed=True)}", f"{text['new_margin']}: {cls.format_number(evaluation.margin_pct)}%"])

        lines.extend(["", f'<a href="{escape(listing.url, quote=True)}">{text["open"]}</a>'])
        message = "\n".join(lines)
        if len(message) <= cls.MAX_MESSAGE_LENGTH:
            return message
        return "\n".join([f"🔥 <b>{text['headline']}</b>", f"<b>{cls._short(listing.title, 250)}</b>", f"💰 {text['price']}: <b>{cls.format_money(listing.price, listing.currency)}</b>", f"💵 {text['profit']}: <b>{cls.format_money(evaluation.estimated_profit, listing.currency, signed=True)}</b>", f"⭐ {text['score']}: <b>{cls.format_number(evaluation.flip_score)} / 100</b>", f'<a href="{escape(listing.url, quote=True)}">{text["open"]}</a>'])
