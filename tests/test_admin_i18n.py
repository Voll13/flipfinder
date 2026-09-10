from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_admin_i18n_catalogs_cover_main_navigation_and_statuses():
    source = (ROOT / "app" / "static" / "admin.js").read_text(encoding="utf-8")
    for language in ("ru", "pl"):
        assert f"{language}:{{" in source
        for key in ("nav_dashboard", "nav_opportunities", "nav_market", "nav_runs", "nav_logs", "nav_settings", "start", "stop", "stopped", "running"):
            assert f"{key}:" in source


def test_admin_i18n_persists_client_language_without_changing_api_values():
    source = (ROOT / "app" / "static" / "admin.js").read_text(encoding="utf-8")
    assert "localStorage.getItem('flipfinder_language')" in source
    assert "localStorage.setItem('flipfinder_language',language)" in source
    assert "translateValue(x.condition)" in source
    assert "api('/api/market')" in source


def test_telegram_report_language_ui_is_independent_from_panel_language():
    source = (ROOT / "app" / "static" / "admin.js").read_text(encoding="utf-8")
    assert "telegram_report_language" in source
    assert "data-report=\"ru\"" in source and "data-report=\"pl\"" in source
    assert "independentLanguage" in source
    assert "localStorage.setItem('flipfinder_language',language)" in source
