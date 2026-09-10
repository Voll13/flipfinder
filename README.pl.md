# FlipFinder

[English](README.md) | [Русский](README.ru.md) | **Polski**

Open-source platforma do analizy okazji na marketplace’ach.

**Profil v1: iPhone na OLX Poland.** FlipFinder łączy trwały benchmark rynku, analizę ryzyka AI, deterministyczną wycenę odsprzedaży i scoring rentowności.

## Szybki start w Windows

```powershell
git clone https://github.com/Voll13/flipfinder.git
cd flipfinder
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m app.admin
```

Otwórz [http://127.0.0.1:8000](http://127.0.0.1:8000), skonfiguruj monitoring i uruchom go z panelu. Wymagane są Python 3.11+, Google Chrome oraz klucz Groq/OpenAI-compatible. Do prawdziwych alertów dodaj token i chat ID Telegrama w lokalnym `.env`.

## Funkcje

- Monitoring OLX Poland przez zwykłą lokalną przeglądarkę.
- Persistent market universe 72h i benchmarki model/storage/condition.
- Pre-AI ranking, analiza semantyczna AI i deterministic resale.
- Scoring rentowności, sygnały ryzyka i price-drop handling.
- Raporty Telegram RU/PL oraz Web Control Center RU/PL.
- Manual review, favorites, notes, comparison, market history i trend dashboard.

## CLI monitor

```powershell
python -m app.main --monitor --interval 15 --market-pages 5 --query "iPhone 13" --query "iPhone 14" --query "iPhone 15" --query "iPhone 16" --limit 5
```

`python -m app.main --version` pokazuje wersję.

## Odpowiedzialne użycie

FlipFinder nie gwarantuje bezpieczeństwa ani zysku. Samodzielnie sprawdzaj sprzedawcę, własność urządzenia, IMEI, iCloud, Face ID, płatność, stan fizyczny i zasady marketplace’u. Wyniki AI mają charakter doradczy.

Projekt nie używa CAPTCHA bypass, stealth evasion, proxy bypass ani cookie theft. W razie challenge zatrzymaj działanie bezpiecznie.

## Wsparcie i indywidualna konfiguracja

FlipFinder pozostaje darmowym projektem open source.

Jeśli potrzebujesz pomocy z instalacją, konfiguracją lub dostosowaniem FlipFinder do własnego sposobu pracy, dostępna jest indywidualna pomoc.

Usługi:

- instalacja i konfiguracja
- konfiguracja Telegram i Groq
- własne profile wyszukiwania
- reguły monitoringu dla konkretnych produktów
- integracje z dodatkowymi marketplace
- prywatna personalizacja i automatyzacja
- dostosowanie do potrzeb biznesowych

[![Kontakt na Telegramie](https://img.shields.io/badge/Kontakt%20na-Telegram-229ED9?logo=telegram&logoColor=white)](https://t.me/t00116)
[![Projekty Mafia DEV](https://img.shields.io/badge/Mafia%20DEV-Projekty-5B5BD6)](https://t.me/ProjectMafia)

Płatna pomoc jest usługą opcjonalną. Wersja open-source FlipFinder pozostaje bezpłatna.

## Licencja

FlipFinder jest udostępniany na licencji GNU Affero General Public License v3.0 (AGPL-3.0-only).

Szczegóły znajdują się w pliku [LICENSE](LICENSE).

Więcej: [README English](README.md), [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [ROADMAP.md](ROADMAP.md).
