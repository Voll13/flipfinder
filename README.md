# FlipFinder

**English** | [Русский](README.ru.md) | [Polski](README.pl.md)

## Marketplace Opportunity Intelligence

![Release](https://img.shields.io/badge/release-v1.0.0-2f9e74)
![Python](https://img.shields.io/badge/python-3.11%2B-3776ab)
[![Tests](https://github.com/Voll13/flipfinder/actions/workflows/tests.yml/badge.svg)](https://github.com/Voll13/flipfinder/actions/workflows/tests.yml)
![License](https://img.shields.io/badge/license-AGPL--3.0--only-8a2be2)
[![GitHub Stars](https://img.shields.io/github/stars/Voll13/flipfinder?style=flat&label=stars)](https://github.com/Voll13/flipfinder/stargazers)

Open-source marketplace opportunity intelligence platform.

**Current v1: iPhone deals on OLX Poland.** FlipFinder finds potentially undervalued listings using persistent market benchmarks, AI-assisted risk analysis, deterministic resale estimation, and profitability scoring.

**Vision:** configurable product profiles across multiple marketplaces. This is future direction, not a v1 capability.

![FlipFinder dashboard](docs/screenshots/dashboard-ru.png)

## What it does

- Monitors OLX Poland through ordinary local browser automation.
- Maintains a 72-hour market universe with model, storage, and condition benchmarks.
- Ranks market-eligible listings before AI analysis.
- Uses Groq-compatible AI for semantic device and risk signals.
- Calculates deterministic resale and profitability scores.
- Sends localized RU/PL Telegram reports for genuine flip candidates.
- Provides a local RU/PL Web Control Center with review, favorites, comparison, market history, trends, and price-drop handling.

## How it works

```mermaid
flowchart TD
  A[OLX Poland] --> B[Browser collector]
  B --> C[Normalization]
  C --> D[Persistent market universe]
  D --> E[Benchmark and pre-AI ranking]
  E --> F[AI semantic analysis]
  F --> G[Deterministic resale]
  G --> H[Profitability scoring]
  H --> I[Telegram alerts]
  H --> J[Web Admin]
```

## Quick start on Windows

1. Install Python 3.11+ and Google Chrome.
2. Clone the repository and enter it:

   ```powershell
   git clone https://github.com/Voll13/flipfinder.git
   cd flipfinder
   ```

3. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

4. Create local configuration:

   ```powershell
   Copy-Item .env.example .env
   ```

5. In `.env`, set a Groq/OpenAI-compatible API key. To receive real alerts, also configure your Telegram bot token and chat ID. Never commit this file.
6. Start the recommended local Web Admin:

   ```powershell
   python -m app.admin
   ```

7. Open [http://127.0.0.1:8000](http://127.0.0.1:8000), configure monitoring, then start it from the panel.

## Supported running modes

Web Admin is recommended for normal use. The CLI monitor is available for controlled local operation:

```powershell
python -m app.main --monitor --interval 15 --market-pages 5 --query "iPhone 13" --query "iPhone 14" --query "iPhone 15" --query "iPhone 16" --limit 5
```

Use `python -m app.main --version` to show the release version.

## Screenshots

| Dashboard | Market | Settings |
| --- | --- | --- |
| ![Dashboard](docs/screenshots/dashboard-ru.png) | ![Market](docs/screenshots/market-ru.png) | ![Settings](docs/screenshots/settings-ru.png) |

The repository includes only reviewed UI screenshots. It does not include production databases, logs, browser profiles, or credentials.

## Responsible use

FlipFinder does not guarantee that a listing is safe or profitable. AI and risk output are advisory only. Independently verify the seller, device ownership, IMEI, iCloud and Face ID status, payment method, physical condition, and current marketplace rules before acting.

## Support & Custom Setup

FlipFinder is free and open source.

Star and share the repository, report bugs, and contribute improvements to support the Community edition.

If you need help with installation, configuration, or adapting FlipFinder to your workflow, custom assistance is available.

Possible services:

- Installation and configuration
- Telegram / Groq setup
- Custom search profiles
- Product-specific monitoring rules
- Marketplace integrations
- Private customization and automation
- Business-specific adaptations

[![Contact on Telegram](https://img.shields.io/badge/Contact%20on-Telegram-229ED9?logo=telegram&logoColor=white)](https://t.me/t00116)
[![Mafia DEV Projects](https://img.shields.io/badge/Mafia%20DEV-Projects-5B5BD6)](https://t.me/ProjectMafia)

Commercial assistance is optional. The open-source FlipFinder Community edition remains free.

## License

FlipFinder is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0-only).

See [LICENSE](LICENSE) for details.

## Marketplace compliance

FlipFinder uses ordinary browser automation only. It does not implement CAPTCHA solving, stealth or fingerprint evasion, proxy bypass, cookie theft, or challenge retry loops. If a marketplace blocks or challenges access, stop and handle it safely.

## Limitations

- v1 supports OLX Poland and an iPhone-focused profile.
- The local machine must remain running while monitoring.
- An AI provider is required for semantic analysis and localized AI free-text.
- Marketplace HTML and embedded state can change.

## Contributing and security

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [ROADMAP.md](ROADMAP.md), and [the v1.0.0 release notes](docs/release-v1.0.0.md).
