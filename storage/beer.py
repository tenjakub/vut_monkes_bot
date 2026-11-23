"""Ceny točeného piva v hospodách (/cena-piva). Zadat je může kdokoli, proto se nic nepřepisuje: každá změna je
nový řádek (i smazání a vrácení na starší cenu), aktuální cena podniku = jeho poslední řádek.
Kdo cenu zadal, se ukládá, aby šlo dohledat a vrátit nesmysly."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .db import Database

HISTORY_LIMIT = 25  # kolik posledních změn ukázat (a nabídnout k vrácení)


@dataclass(frozen=True)
class BeerEntry:
    id: int
    pub: str
    price: int | None  # None = cena smazaná
    beer: str
    many: bool
    user_id: int
    created_at: datetime
    reverted_from: int | None = None


_COLUMNS = "id, pub, price, beer, many, user_id, created_at, reverted_from"


def _entry(row) -> BeerEntry:
    return BeerEntry(
        row["id"], row["pub"], row["price"], row["beer"], bool(row["many"]), row["user_id"],
        datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M"), row["reverted_from"],
    )


async def add(
    db: Database, pub: str, price: int | None, beer: str, many: bool, user_id: int, now: datetime,
    reverted_from: int | None = None,
) -> BeerEntry:
    async with db.transaction() as tx:
        cursor = await tx.execute(
            "INSERT INTO beer_price (pub, price, beer, many, user_id, created_at, reverted_from) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pub, price, beer, int(many), user_id, now.strftime("%Y-%m-%d %H:%M"), reverted_from),
        )
        new_id = cursor.lastrowid
    return BeerEntry(new_id, pub, price, beer, many, user_id, now.replace(second=0, microsecond=0), reverted_from)


async def revert(db: Database, entry: BeerEntry, user_id: int, now: datetime) -> BeerEntry:
    """Vrátí podnik na starší záznam: přidá jeho kopii (historie zůstane celá)."""
    return await add(db, entry.pub, entry.price, entry.beer, entry.many, user_id, now, reverted_from=entry.id)


async def current(db: Database) -> dict[str, BeerEntry]:
    """Aktuální ceny všech podniků, které nějakou mají (smazané ne)."""
    rows = await db.fetchall(
        f"SELECT {_COLUMNS} FROM beer_price WHERE id IN (SELECT MAX(id) FROM beer_price GROUP BY pub)"
    )
    return {r["pub"]: _entry(r) for r in rows if r["price"] is not None}


async def history(db: Database, pub: str, limit: int = HISTORY_LIMIT) -> list[BeerEntry]:
    """Poslední změny podniku, nejnovější první (první = aktuální stav)."""
    rows = await db.fetchall(f"SELECT {_COLUMNS} FROM beer_price WHERE pub = ? ORDER BY id DESC LIMIT ?", (pub, limit))
    return [_entry(r) for r in rows]


async def get(db: Database, entry_id: int) -> BeerEntry | None:
    row = await db.fetchone(f"SELECT {_COLUMNS} FROM beer_price WHERE id = ?", (entry_id,))
    return _entry(row) if row else None
