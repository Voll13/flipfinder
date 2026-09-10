# FlipFinder

[English](README.md) | **Русский** | [Polski](README.pl.md)

Open-source платформа анализа выгодных предложений на маркетплейсах.

**Профиль v1: iPhone на OLX Poland.** FlipFinder использует persistent market benchmarks, AI-сигналы риска, deterministic resale и scoring для поиска потенциально выгодных объявлений.

## Быстрый старт для Windows

```powershell
git clone https://github.com/YOUR-ACCOUNT/flipfinder.git
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

## Лицензия

FlipFinder распространяется по лицензии GNU Affero General Public License v3.0 (AGPL-3.0-only).

Подробности см. в [LICENSE](LICENSE).

Подробнее: [README English](README.md), [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [ROADMAP.md](ROADMAP.md).
