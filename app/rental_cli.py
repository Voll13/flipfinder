"""Offline command-line ingest for saved OLX rental search pages."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.config import Settings
from app.storage.database import Database
from app.storage.rental_repository import RentalRepository
from app.verticals.rental.ingest import RentalIngestService


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest saved OLX rental search HTML")
    parser.add_argument("--html-file", action="append", required=True, metavar="PATH", help="saved OLX search HTML; repeatable")
    parser.add_argument("--database", metavar="PATH", help="SQLite database path override")
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    settings = Settings()
    async with Database(args.database or settings.database_path) as database:
        summary = await RentalIngestService(RentalRepository(database)).ingest_html_files(
            [Path(path) for path in args.html_file],
        )
    print("Rental ingest complete")
    print(f"files={summary.files_processed}")
    print(f"parsed={summary.parsed_count}")
    print(f"unique={summary.unique_count}")
    print(f"new={summary.new_count}")
    print(f"updated={summary.updated_count}")
    print(f"duplicates={summary.duplicate_count}")
    print(f"conflicts={summary.conflict_count}")


if __name__ == "__main__":
    asyncio.run(main())
