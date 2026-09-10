import pytest
from unittest.mock import AsyncMock

import app.main as main_module
from app.config import Settings
from app.exceptions import ConfigurationError
from app.main import OfflineOLXScraper, parse_args
from app.scrapers.olx import OLXScraper
from app.version import VERSION


def test_parse_args_supports_dry_run_pages_and_repeated_queries():
    args = parse_args(["--dry-run", "--pages", "2", "--limit", "3", "--html-file", "page.html", "--database", "test.db", "--query", "iPhone 15", "--query", "iPhone 14"])
    assert args.dry_run and args.pages == 2 and args.limit == 3 and args.html_file == "page.html" and args.database == "test.db" and args.query == ["iPhone 15", "iPhone 14"]


def test_parse_args_selects_browser_mode():
    assert parse_args(["--browser"]).browser is True


def test_parse_args_accepts_external_id():
    assert parse_args(["--external-id", "1095620361"]).external_id == "1095620361"


def test_parse_args_market_pages_default_and_override():
    assert parse_args([]).market_pages is None
    assert parse_args(["--browser", "--market-pages", "3"]).market_pages == 3


def test_monitor_args_and_interval_validation():
    args = parse_args(["--monitor", "--interval", "15", "--model", "iPhone 15 Pro", "--city", "Opole", "--voivodeship", "opolskie"])
    assert args.monitor and args.interval == 15 and args.model == ["iPhone 15 Pro"] and args.city == ["Opole"]


def test_parse_args_supports_telegram_test():
    assert parse_args(["--telegram-test"]).telegram_test is True


def test_parse_args_supports_market_only():
    assert parse_args(["--browser", "--market-only"]).market_only is True


def test_version_flag_uses_the_single_release_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        parse_args(["--version"])
    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"FlipFinder {VERSION}"


def test_parse_args_defaults_to_settings_values_in_pipeline():
    args = parse_args([])
    assert args.query is None and args.pages is None and args.limit is None and not args.dry_run


@pytest.mark.asyncio
async def test_main_fails_before_scraping_when_openai_configuration_is_missing(monkeypatch):
    class Resource:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    monkeypatch.setattr(main_module, "Settings", lambda: Settings(_env_file=None))
    monkeypatch.setattr(main_module, "Database", lambda path: Resource())
    monkeypatch.setattr(main_module, "OLXScraper", lambda configured: Resource())
    with pytest.raises(ConfigurationError, match="OPENAI_API_KEY"):
        await main_module.main(["--dry-run"])


@pytest.mark.asyncio
async def test_telegram_test_uses_notifier_only_and_does_not_create_pipeline_resources(monkeypatch):
    settings = Settings(_env_file=None, telegram_bot_token="token", telegram_chat_id="123")
    events = []

    class Notifier:
        async def __aenter__(self):
            events.append("enter")
            return self
        async def __aexit__(self, *args):
            events.append("exit")
        async def send_test_message(self):
            events.append("send")
            return type("Message", (), {"message_id": 1})()

    monkeypatch.setattr(main_module, "Settings", lambda: settings)
    monkeypatch.setattr(main_module, "TelegramNotifier", lambda configured: Notifier())
    for name in ("Database", "OLXScraper", "AIAnalyzer", "MarketDataProvider"):
        monkeypatch.setattr(main_module, name, lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError(name)))
    await main_module.main(["--telegram-test"])
    assert events == ["enter", "send", "exit"]


@pytest.mark.asyncio
async def test_telegram_test_requires_token_and_chat_id(monkeypatch):
    monkeypatch.setattr(main_module, "Settings", lambda: Settings(_env_file=None, telegram_chat_id="123"))
    with pytest.raises(ConfigurationError, match="TELEGRAM_BOT_TOKEN"):
        await main_module.main(["--telegram-test"])
    monkeypatch.setattr(main_module, "Settings", lambda: Settings(_env_file=None, telegram_bot_token="token"))
    with pytest.raises(ConfigurationError, match="TELEGRAM_CHAT_ID"):
        await main_module.main(["--telegram-test"])


@pytest.mark.asyncio
async def test_offline_scraper_uses_saved_html_without_http(tmp_path):
    source = """<script id=\"olx-init-config\">window.__PRERENDERED_STATE__ = \"{\\\"listing\\\": {\\\"listing\\\": {\\\"ads\\\": [{\\\"id\\\": 1, \\\"urlPath\\\": \\\"/one\\\", \\\"title\\\": \\\"iPhone 15 Pro\\\", \\\"price\\\": {\\\"regularPrice\\\": {\\\"value\\\": \\\"1000\\\", \\\"currencyCode\\\": \\\"PLN\\\"}}}]}}}\";</script>"""
    path = tmp_path / "saved.html"
    path.write_text(source, encoding="utf-8")
    parser = OLXScraper(Settings(_env_file=None))
    parser._request = AsyncMock()  # type: ignore[method-assign]
    offline = OfflineOLXScraper(parser, str(path))
    assert [item.external_id for item in await offline.search("iphone 15 pro")] == ["1"]
    parser._request.assert_not_awaited()
