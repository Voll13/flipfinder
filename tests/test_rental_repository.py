from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

from app.storage.database import Database
from app.storage.rental_repository import RentalRepository
from app.verticals.rental.models import RentalListing, RentalProfile


def now(offset: int = 0) -> datetime:
    return datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(minutes=offset)


def listing(**changes) -> RentalListing:
    data = {
        "source": "olx", "source_listing_id": "ad-1", "canonical_url": "https://www.olx.pl/d/oferta/ad-1",
        "title": "Mieszkanie Opole", "city": "Opole", "rent_price_pln": 3300,
        "first_seen_at": now(), "last_seen_at": now(),
    }
    data.update(changes)
    return RentalListing(**data)


def profile(**changes) -> RentalProfile:
    data = {
        "key": "olx-rental-opole", "marketplace": "olx", "source_city": "Opole",
        "display_name_ru": "ОПОЛЕ", "search_url": "https://example.test/opole", "destination_key": "rentals-opole",
    }
    data.update(changes)
    return RentalProfile(**data)


@pytest_asyncio.fixture
async def repo(tmp_path):
    async with Database(str(tmp_path / "rental.db")) as database:
        yield RentalRepository(database)


@pytest.mark.asyncio
async def test_profile_bootstrap_state_is_persistent_and_not_overwritten(repo: RentalRepository):
    stored = await repo.upsert_profile(profile())
    assert stored.bootstrap_completed_at is None
    completed = await repo.mark_profile_bootstrap_completed(stored.key, now(10))
    repeated = await repo.mark_profile_bootstrap_completed(stored.key, now(20))
    assert completed and repeated
    assert repeated.bootstrap_completed_at == now(10)


@pytest.mark.asyncio
async def test_listing_uniqueness_upsert_preserves_first_seen_and_updates_last_seen(repo: RentalRepository):
    listing_id, created = await repo.upsert_listing(listing())
    same_id, created_again = await repo.upsert_listing(listing(title="Updated title", last_seen_at=now(5), first_seen_at=now(5)))
    stored = await repo.get_listing_by_source_id("olx", "ad-1")
    other_source_id, other_created = await repo.upsert_listing(listing(source="other", last_seen_at=now(6)))
    assert created and not created_again and listing_id == same_id
    assert stored and stored.first_seen_at == now() and stored.last_seen_at == now(5) and stored.title == "Updated title"
    assert other_created and other_source_id != listing_id


@pytest.mark.asyncio
async def test_price_history_records_initial_and_changed_price_only(repo: RentalRepository):
    listing_id, _ = await repo.upsert_listing(listing())
    await repo.upsert_listing(listing(last_seen_at=now(1)))
    await repo.upsert_listing(listing(rent_price_pln=3100, last_seen_at=now(2)))
    await repo.upsert_listing(listing(rent_price_pln=3100, last_seen_at=now(3)))
    assert [row["rent_price_pln"] for row in await repo.get_price_history(listing_id)] == [3300, 3100]


@pytest.mark.asyncio
async def test_publication_uniqueness_destinations_and_state_transitions(repo: RentalRepository):
    listing_id, _ = await repo.upsert_listing(listing())
    first = await repo.create_or_claim_publication(listing_id, "rentals-opole")
    duplicate = await repo.create_or_claim_publication(listing_id, "rentals-opole")
    other_destination = await repo.create_or_claim_publication(listing_id, "rentals-warszawa")
    sent = await repo.mark_publication_sent(first.publication.id, 42)
    failed = await repo.mark_publication_failed(other_destination.publication.id, "temporary failure")
    uncertain = await repo.mark_publication_uncertain(other_destination.publication.id, "delivery status unknown")
    assert first.claimed and not duplicate.claimed and other_destination.claimed
    assert sent and sent.status == "sent" and sent.telegram_message_id == 42 and sent.sent_at is not None
    assert failed and failed.status == "failed" and failed.last_error == "temporary failure"
    assert uncertain and uncertain.status == "uncertain" and uncertain.last_error == "delivery status unknown"
