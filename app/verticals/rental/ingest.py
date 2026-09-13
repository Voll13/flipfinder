"""Offline persistence flow for saved OLX rental search pages."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from app.marketplaces.olx.rental_parser import OLXRentalParser
from app.storage.rental_repository import RentalRepository
from app.verticals.rental.models import RentalListing


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RentalIngestSummary:
    files_processed: int
    parsed_count: int
    unique_count: int
    new_count: int
    updated_count: int
    duplicate_count: int
    conflict_count: int


class RentalIngestService:
    """Read saved search HTML and persist normalized listings without acquisition."""

    def __init__(self, repository: RentalRepository, parser: OLXRentalParser | None = None) -> None:
        self._repository = repository
        self._parser = parser or OLXRentalParser()

    async def ingest_html_files(
        self, html_files: Sequence[str | Path], *, observed_at: datetime | None = None,
    ) -> RentalIngestSummary:
        if not html_files:
            raise ValueError("at least one rental HTML file is required")

        seen_at = observed_at or datetime.now(timezone.utc)
        parsed: list[RentalListing] = []
        for file_name in html_files:
            path = Path(file_name)
            listings = self._parser.parse_search_html(path.read_text(encoding="utf-8"), seen_at)
            if not listings:
                raise ValueError(f"rental HTML contains no listings: {path}")
            parsed.extend(listings)

        unique: dict[tuple[str, str], RentalListing] = {}
        duplicates = conflicts = 0
        for listing in parsed:
            key = (listing.source, listing.source_listing_id)
            previous = unique.get(key)
            if previous is None:
                unique[key] = listing
                continue
            duplicates += 1
            if previous != listing:
                conflicts += 1
                logger.warning("Duplicate rental listing conflict for %s:%s; keeping first occurrence", *key)

        new_count = updated_count = 0
        for listing in unique.values():
            _, is_new = await self._repository.upsert_listing(listing)
            if is_new:
                new_count += 1
            else:
                updated_count += 1

        return RentalIngestSummary(
            files_processed=len(html_files), parsed_count=len(parsed), unique_count=len(unique),
            new_count=new_count, updated_count=updated_count, duplicate_count=duplicates,
            conflict_count=conflicts,
        )
