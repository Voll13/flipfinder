from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest
import pytest_asyncio

from app.marketplaces.olx.embedded_state import extract_prerendered_state
from app.storage.database import Database
from app.storage.rental_repository import RentalRepository
from app.verticals.rental.ingest import RentalIngestService
from app.verticals.rental.models import RentalProfile


def html_from_state(state: dict) -> str:
    return '<script id="olx-init-config">window.__PRERENDERED_STATE__ = ' + json.dumps(json.dumps(state)) + ";</script>"


def synthetic_state() -> dict:
    return json.loads(Path("tests/fixtures/olx_rental_raw_synthetic.json").read_text(encoding="utf-8"))


def write_page(path: Path, state: dict) -> Path:
    path.write_text(html_from_state(state), encoding="utf-8")
    return path


@pytest_asyncio.fixture
async def repository(tmp_path: Path):
    async with Database(str(tmp_path / "rental-ingest.db")) as database:
        yield RentalRepository(database)


def profile() -> RentalProfile:
    return RentalProfile(
        key="opole", marketplace="olx", source_city="Opole", display_name_ru="ОПОЛЕ",
        search_url="https://example.test/opole", destination_key="rentals-opole",
    )


async def count(repository: RentalRepository, table: str) -> int:
    row = await (await repository._database._require_connection().execute(f"SELECT COUNT(*) AS count FROM {table}")).fetchone()
    return int(row["count"])


@pytest.mark.asyncio
async def test_ingests_one_saved_page_and_creates_no_publications_or_profiles(repository: RentalRepository, tmp_path: Path):
    result = await RentalIngestService(repository).ingest_html_files([write_page(tmp_path / "page1.html", synthetic_state())])
    assert (result.files_processed, result.parsed_count, result.unique_count, result.new_count, result.updated_count) == (1, 1, 1, 1, 0)
    assert await count(repository, "rental_listings") == 1
    assert await count(repository, "rental_price_history") == 1
    assert await count(repository, "rental_publications") == 0
    assert await count(repository, "rental_profiles") == 0


@pytest.mark.asyncio
async def test_multiple_files_deduplicate_conflicts_and_keep_first_deterministically(repository: RentalRepository, tmp_path: Path):
    page1 = synthetic_state()
    page2 = deepcopy(page1)
    page2["listing"]["listing"]["ads"][0]["price"]["regularPrice"]["value"] = "3400"
    second = deepcopy(page1)
    second["listing"]["listing"]["ads"][0]["id"] = "rental-101"
    page2["listing"]["listing"]["ads"].append(second["listing"]["listing"]["ads"][0])
    result = await RentalIngestService(repository).ingest_html_files([
        write_page(tmp_path / "page1.html", page1), write_page(tmp_path / "page2.html", page2),
    ])
    assert (result.files_processed, result.parsed_count, result.unique_count) == (2, 3, 2)
    assert (result.new_count, result.duplicate_count, result.conflict_count) == (2, 1, 1)
    stored = await repository.get_listing_by_source_id("olx", "rental-100")
    assert stored and stored.rent_price_pln == 3300


@pytest.mark.asyncio
async def test_repeated_ingest_preserves_first_seen_updates_last_seen_and_only_records_price_changes(repository: RentalRepository, tmp_path: Path):
    page = tmp_path / "page.html"
    state = synthetic_state()
    write_page(page, state)
    service = RentalIngestService(repository)
    first_time = datetime(2026, 9, 10, tzinfo=timezone.utc)
    second_time = first_time + timedelta(minutes=5)
    first = await service.ingest_html_files([page], observed_at=first_time)
    second = await service.ingest_html_files([page], observed_at=second_time)
    item = await repository.get_listing_by_source_id("olx", "rental-100")
    assert (first.new_count, second.new_count, second.updated_count) == (1, 0, 1)
    assert item and item.first_seen_at == first_time and item.last_seen_at == second_time
    assert len(await repository.get_price_history(1)) == 1

    state["listing"]["listing"]["ads"][0]["price"]["regularPrice"]["value"] = "3400"
    write_page(page, state)
    third = await service.ingest_html_files([page], observed_at=second_time + timedelta(minutes=5))
    assert third.new_count == 0 and third.updated_count == 1
    assert len(await repository.get_price_history(1)) == 2
    assert await count(repository, "rental_publications") == 0


@pytest.mark.asyncio
async def test_ingest_does_not_change_existing_profile_bootstrap_state(repository: RentalRepository, tmp_path: Path):
    await repository.upsert_profile(profile())
    await RentalIngestService(repository).ingest_html_files([write_page(tmp_path / "page.html", synthetic_state())])
    stored = await repository.get_profile("opole")
    assert stored and stored.bootstrap_completed_at is None


@pytest.mark.asyncio
async def test_missing_malformed_or_empty_files_fail_explicitly(repository: RentalRepository, tmp_path: Path):
    service = RentalIngestService(repository)
    with pytest.raises(FileNotFoundError):
        await service.ingest_html_files([tmp_path / "missing.html"])
    malformed = tmp_path / "malformed.html"
    malformed.write_text("<html></html>", encoding="utf-8")
    with pytest.raises(Exception, match="OLX __PRERENDERED_STATE__"):
        await service.ingest_html_files([malformed])
    empty = synthetic_state()
    empty["listing"]["listing"]["ads"] = []
    with pytest.raises(ValueError, match="contains no listings"):
        await service.ingest_html_files([write_page(tmp_path / "empty.html", empty)])
