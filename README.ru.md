# FlipFinder

[English](README.md) | **Русский** | [Polski](README.pl.md)

Open-source платформа анализа выгодных предложений на маркетплейсах.

**Профиль v1: iPhone на OLX Poland.** FlipFinder использует persistent market benchmarks, AI-сигналы риска, deterministic resale и scoring для поиска потенциально выгодных объявлений.

Нужна помощь с установкой или кастомизацией?

[![Связаться в Telegram](https://img.shields.io/badge/Связаться%20в-Telegram-229ED9?logo=telegram&logoColor=white)](https://t.me/t00116)

## Быстрый старт для Windows

```powershell
git clone https://github.com/Voll13/flipfinder.git
cd flipfinder
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.admin
```

Откройте [http://127.0.0.1:8000](http://127.0.0.1:8000), настройте мониторинг и запустите его из панели. Нужны Python 3.11+, Google Chrome и Groq/OpenAI-compatible API key. Для настоящих alert добавьте Telegram token и chat ID в локальный `.env`.

## Возможности

- OLX Poland monitoring через обычный локальный браузер.
- Persistent 72h market universe и benchmarks по model/storage/condition.
- Pre-AI ranking, semantic AI analysis и deterministic resale.
- Profitability scoring, fraud/risk signals и price-drop handling.
- RU/PL Telegram reports и RU/PL Web Control Center.
- Manual review, favorites, notes, comparison, market history и trend dashboard.

## Запуск через CLI

```powershell
python -m app.main --monitor --interval 15 --market-pages 5 --query "iPhone 13" --query "iPhone 14" --query "iPhone 15" --query "iPhone 16" --limit 5
```

`python -m app.main --version` показывает версию.

## Ответственное использование

FlipFinder не гарантирует безопасность или прибыльность сделки. Проверяйте продавца, ownership, IMEI, iCloud, Face ID, оплату, физическое состояние и правила площадки самостоятельно. AI output имеет advisory характер.

Не используется CAPTCHA bypass, stealth evasion, proxy bypass или cookie theft. При challenge остановите работу безопасно.

## Поддержка и индивидуальная настройка

FlipFinder остаётся бесплатным open-source проектом.

Если нужна помощь с установкой, настройкой или адаптацией FlipFinder под конкретную задачу, можно заказать индивидуальную помощь.

Услуги:

- установка и настройка
- подключение Telegram и Groq
- индивидуальные поисковые профили
- правила мониторинга под конкретные товары
- интеграция новых площадок
- частная кастомизация и автоматизация
- адаптация под бизнес-задачи

[![Связаться в Telegram](https://img.shields.io/badge/Связаться%20в-Telegram-229ED9?logo=telegram&logoColor=white)](https://t.me/t00116)
[![Проекты Mafia DEV](https://img.shields.io/badge/Mafia%20DEV-Проекты-5B5BD6)](https://t.me/ProjectMafia)

Платная помощь является дополнительной услугой. Open-source версия FlipFinder остаётся бесплатной.

## Лицензия

FlipFinder распространяется по лицензии GNU Affero General Public License v3.0 (AGPL-3.0-only).

Подробности см. в [LICENSE](LICENSE).

Подробнее: [README English](README.md), [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [ROADMAP.md](ROADMAP.md).
