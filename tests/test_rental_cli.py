import pytest

from app.rental_cli import parse_args


def test_rental_cli_accepts_repeatable_html_files_and_database():
    args = parse_args(["--html-file", "one.html", "--html-file", "two.html", "--database", "temp.db"])
    assert args.html_file == ["one.html", "two.html"] and args.database == "temp.db"


def test_rental_cli_requires_html_file():
    with pytest.raises(SystemExit):
        parse_args([])
