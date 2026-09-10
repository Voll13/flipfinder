"""SQLite persistence primitives for the future Rental vertical."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from app.verticals.rental.models import RentalListing, RentalProfile, RentalPublication

if TYPE_CHECKING:
    from app.storage.database import Database


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _decimal(value: Decimal | None) -> str | None:
    return str(value) if value is not None else None


def _as_bool(value: bool | None) -> int | None:
    return None if value is None else int(value)


@dataclass(frozen=True)
class PublicationClaim:
    publication: RentalPublication
    claimed: bool


class RentalRepository:
    """Small repository over the existing async SQLite connection lifecycle."""

    def __init__(self, database: Database) -> None:
        self._database = database

    @staticmethod
    def _profile_from_row(row: Any) -> RentalProfile:
        return RentalProfile(
            key=row["profile_key"], marketplace=row["marketplace"], vertical=row["vertical"],
            country_code=row["country_code"], source_city=row["source_city"],
            display_name_ru=row["display_name_ru"], search_url=row["search_url"],
            destination_key=row["destination_key"], enabled=bool(row["enabled"]),
            bootstrap_completed_at=datetime.fromisoformat(row["bootstrap_completed_at"]) if row["bootstrap_completed_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]), updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    @staticmethod
    def _listing_from_row(row: Any) -> RentalListing:
        return RentalListing(
            source=row["source"], source_listing_id=row["source_listing_id"], canonical_url=row["canonical_url"],
            title=row["title"], country_code=row["country_code"], city=row["city"], rent_price_pln=row["rent_price_pln"],
            first_seen_at=datetime.fromisoformat(row["first_seen_at"]), last_seen_at=datetime.fromisoformat(row["last_seen_at"]),
            is_active=bool(row["is_active"]), published_at=datetime.fromisoformat(row["published_at"]) if row["published_at"] else None,
            district=row["district"], address_text=row["address_text"],
            latitude=Decimal(row["latitude"]) if row["latitude"] is not None else None,
            longitude=Decimal(row["longitude"]) if row["longitude"] is not None else None,
            property_type=row["property_type"], rooms=Decimal(row["rooms"]) if row["rooms"] is not None else None,
            area_m2=Decimal(row["area_m2"]) if row["area_m2"] is not None else None,
            floor_label=row["floor_label"], total_floors=row["total_floors"], admin_fee_pln=row["admin_fee_pln"],
            utilities_text=row["utilities_text"], deposit_pln=row["deposit_pln"], furnished=None if row["furnished"] is None else bool(row["furnished"]),
            balcony=None if row["balcony"] is None else bool(row["balcony"]), elevator=None if row["elevator"] is None else bool(row["elevator"]),
            parking=None if row["parking"] is None else bool(row["parking"]), pets_policy=row["pets_policy"], advertiser_type=row["advertiser_type"],
            agency_name=row["agency_name"], description=row["description"], image_urls=json.loads(row["image_urls"] or "[]"),
            main_image_url=row["main_image_url"], source_attributes=json.loads(row["source_attributes_json"] or "{}"),
        )

    @staticmethod
    def _publication_from_row(row: Any) -> RentalPublication:
        return RentalPublication(
            id=row["id"], rental_listing_id=row["rental_listing_id"], destination_key=row["destination_key"], status=row["status"],
            telegram_message_id=row["telegram_message_id"], created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]), sent_at=datetime.fromisoformat(row["sent_at"]) if row["sent_at"] else None,
            last_error=row["last_error"],
        )

    async def upsert_profile(self, profile: RentalProfile) -> RentalProfile:
        now = _utc_now()
        conn = self._database._require_connection()
        async with self._database._lock:
            await conn.execute(
                """INSERT INTO rental_profiles(profile_key,marketplace,vertical,country_code,source_city,display_name_ru,search_url,destination_key,enabled,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(profile_key) DO UPDATE SET marketplace=excluded.marketplace,vertical=excluded.vertical,country_code=excluded.country_code,source_city=excluded.source_city,display_name_ru=excluded.display_name_ru,search_url=excluded.search_url,destination_key=excluded.destination_key,enabled=excluded.enabled,updated_at=excluded.updated_at""",
                (profile.key, profile.marketplace, profile.vertical, profile.country_code, profile.source_city, profile.display_name_ru,
                 profile.search_url, profile.destination_key, int(profile.enabled), _iso(now), _iso(now)),
            )
            await conn.commit()
        stored = await self.get_profile(profile.key)
        assert stored is not None
        return stored

    async def get_profile(self, key: str) -> RentalProfile | None:
        row = await (await self._database._require_connection().execute("SELECT * FROM rental_profiles WHERE profile_key=?", (key,))).fetchone()
        return self._profile_from_row(row) if row else None

    async def mark_profile_bootstrap_completed(self, key: str, completed_at: datetime | None = None) -> RentalProfile | None:
        now = completed_at or _utc_now()
        conn = self._database._require_connection()
        async with self._database._lock:
            await conn.execute(
                "UPDATE rental_profiles SET bootstrap_completed_at=COALESCE(bootstrap_completed_at,?),updated_at=? WHERE profile_key=?",
                (_iso(now), _iso(now), key),
            )
            await conn.commit()
        return await self.get_profile(key)

    @staticmethod
    def _listing_values(listing: RentalListing) -> tuple[object, ...]:
        return (
            listing.canonical_url, listing.title, listing.country_code, listing.city,
            _iso(listing.published_at) if listing.published_at else None, listing.district, listing.address_text,
            _decimal(listing.latitude), _decimal(listing.longitude), listing.property_type, _decimal(listing.rooms),
            _decimal(listing.area_m2), listing.floor_label, listing.total_floors, listing.rent_price_pln,
            listing.admin_fee_pln, listing.utilities_text, listing.deposit_pln, _as_bool(listing.furnished),
            _as_bool(listing.balcony), _as_bool(listing.elevator), _as_bool(listing.parking), listing.pets_policy,
            listing.advertiser_type, listing.agency_name, listing.description, _dump(listing.image_urls),
            listing.main_image_url, _dump(listing.source_attributes), _iso(listing.last_seen_at), int(listing.is_active),
        )

    async def upsert_listing(self, listing: RentalListing) -> tuple[int, bool]:
        """Insert or refresh a source listing while preserving its original first_seen_at."""
        conn = self._database._require_connection()
        now = _utc_now()
        async with self._database._lock:
            row = await (await conn.execute(
                "SELECT id,rent_price_pln FROM rental_listings WHERE source=? AND source_listing_id=?",
                (listing.source, listing.source_listing_id),
            )).fetchone()
            if row is None:
                cursor = await conn.execute(
                    """INSERT INTO rental_listings(source,source_listing_id,canonical_url,title,country_code,city,published_at,district,address_text,latitude,longitude,property_type,rooms,area_m2,floor_label,total_floors,rent_price_pln,admin_fee_pln,utilities_text,deposit_pln,furnished,balcony,elevator,parking,pets_policy,advertiser_type,agency_name,description,image_urls,main_image_url,source_attributes_json,first_seen_at,last_seen_at,is_active,created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (listing.source, listing.source_listing_id, *self._listing_values(listing), _iso(listing.first_seen_at), _iso(now), _iso(now)),
                )
                listing_id = int(cursor.lastrowid)
                await conn.execute(
                    "INSERT INTO rental_price_history(rental_listing_id,rent_price_pln,observed_at) VALUES(?,?,?)",
                    (listing_id, listing.rent_price_pln, _iso(listing.last_seen_at)),
                )
                await conn.commit()
                return listing_id, True

            listing_id = int(row["id"])
            await conn.execute(
                """UPDATE rental_listings SET canonical_url=?,title=?,country_code=?,city=?,published_at=?,district=?,address_text=?,latitude=?,longitude=?,property_type=?,rooms=?,area_m2=?,floor_label=?,total_floors=?,rent_price_pln=?,admin_fee_pln=?,utilities_text=?,deposit_pln=?,furnished=?,balcony=?,elevator=?,parking=?,pets_policy=?,advertiser_type=?,agency_name=?,description=?,image_urls=?,main_image_url=?,source_attributes_json=?,last_seen_at=?,is_active=?,updated_at=? WHERE id=?""",
                (*self._listing_values(listing), _iso(now), listing_id),
            )
            if int(row["rent_price_pln"]) != listing.rent_price_pln:
                await conn.execute(
                    "INSERT INTO rental_price_history(rental_listing_id,rent_price_pln,observed_at) VALUES(?,?,?)",
                    (listing_id, listing.rent_price_pln, _iso(listing.last_seen_at)),
                )
            await conn.commit()
            return listing_id, False

    async def get_listing_by_source_id(self, source: str, source_listing_id: str) -> RentalListing | None:
        row = await (await self._database._require_connection().execute(
            "SELECT * FROM rental_listings WHERE source=? AND source_listing_id=?", (source, source_listing_id),
        )).fetchone()
        return self._listing_from_row(row) if row else None

    async def get_price_history(self, rental_listing_id: int) -> list[dict[str, Any]]:
        rows = await (await self._database._require_connection().execute(
            "SELECT * FROM rental_price_history WHERE rental_listing_id=? ORDER BY observed_at ASC,id ASC", (rental_listing_id,),
        )).fetchall()
        return [dict(row) for row in rows]

    async def create_or_claim_publication(self, rental_listing_id: int, destination_key: str) -> PublicationClaim:
        """Atomically create the one permitted publication row for a destination."""
        conn = self._database._require_connection()
        now = _utc_now()
        async with self._database._lock:
            cursor = await conn.execute(
                "INSERT INTO rental_publications(rental_listing_id,destination_key,status,created_at,updated_at) VALUES(?,?, 'pending',?,?) ON CONFLICT(rental_listing_id,destination_key) DO NOTHING",
                (rental_listing_id, destination_key, _iso(now), _iso(now)),
            )
            claimed = cursor.rowcount == 1
            row = await (await conn.execute(
                "SELECT * FROM rental_publications WHERE rental_listing_id=? AND destination_key=?",
                (rental_listing_id, destination_key),
            )).fetchone()
            await conn.commit()
        assert row is not None
        return PublicationClaim(self._publication_from_row(row), claimed)

    async def _set_publication_status(
        self, publication_id: int, status: str, *, telegram_message_id: int | None = None,
        last_error: str | None = None,
    ) -> RentalPublication | None:
        now = _utc_now()
        conn = self._database._require_connection()
        sent_at = _iso(now) if status == "sent" else None
        async with self._database._lock:
            await conn.execute(
                "UPDATE rental_publications SET status=?,telegram_message_id=?,sent_at=?,last_error=?,updated_at=? WHERE id=?",
                (status, telegram_message_id, sent_at, last_error, _iso(now), publication_id),
            )
            await conn.commit()
        row = await (await conn.execute("SELECT * FROM rental_publications WHERE id=?", (publication_id,))).fetchone()
        return self._publication_from_row(row) if row else None

    async def mark_publication_sent(self, publication_id: int, telegram_message_id: int) -> RentalPublication | None:
        return await self._set_publication_status(publication_id, "sent", telegram_message_id=telegram_message_id)

    async def mark_publication_failed(self, publication_id: int, last_error: str) -> RentalPublication | None:
        return await self._set_publication_status(publication_id, "failed", last_error=last_error)

    async def mark_publication_uncertain(self, publication_id: int, last_error: str) -> RentalPublication | None:
        return await self._set_publication_status(publication_id, "uncertain", last_error=last_error)
