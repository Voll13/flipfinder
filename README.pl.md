# FlipFinder

[English](README.md) | [Русский](README.ru.md) | **Polski**

Open-source platforma do analizy okazji na marketplace’ach.

**Profil v1: iPhone na OLX Poland.** FlipFinder łączy trwały benchmark rynku, analizę ryzyka AI, deterministyczną wycenę odsprzedaży i scoring rentowności.

## Szybki start w Windows

```powershell
git clone https://github.com/YOUR-ACCOUNT/flipfinder.git
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

## Licencja

FlipFinder jest udostępniany na licencji GNU Affero General Public License v3.0 (AGPL-3.0-only).

Szczegóły znajdują się w pliku [LICENSE](LICENSE).

Więcej: [README English](README.md), [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), [ROADMAP.md](ROADMAP.md).
