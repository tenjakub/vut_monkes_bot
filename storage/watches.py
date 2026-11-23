"""Hlídání akcí: co kdo hlídá (`watch`) a o kterých akcích už dostal zprávu (`watch_hit`).

ID uživatele je nutné (komu poslat zprávu). Každé hlídání si člověk může v /hlidat zrušit, tím se smažou i
záznamy o poslaných akcích.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from .db import Database

MAX_PER_USER = 10


@dataclass(frozen=True)
class Watch:
    id: int
    user_id: int
    query: str
    max_price: float | None


class TooMany(ValueError):
    """Člověk už hlídá MAX_PER_USER věcí."""


def _watch(row) -> Watch:
    return Watch(row["id"], row["user_id"], row["query"], row["max_price"])


async def add(db: Database, user_id: int, query: str, max_price: float | None, now: datetime) -> Watch:
    async with db.transaction() as tx:
        cursor = await tx.execute("SELECT COUNT(*) FROM watch WHERE user_id = ?", (user_id,))
        if (await cursor.fetchone())[0] >= MAX_PER_USER:
            raise TooMany(query)
        cursor = await tx.execute(
            "INSERT INTO watch (user_id, query, max_price, created_at) VALUES (?, ?, ?, ?)",
            (user_id, query, max_price, now.strftime("%Y-%m-%d %H:%M")),
        )
        return Watch(cursor.lastrowid, user_id, query, max_price)


async def remove(db: Database, user_id: int, watch_id: int) -> bool:
    """Smaže hlídání (jen vlastní)."""
    return await db.execute("DELETE FROM watch WHERE id = ? AND user_id = ?", (watch_id, user_id)) > 0


async def of_user(db: Database, user_id: int) -> list[Watch]:
    rows = await db.fetchall("SELECT id, user_id, query, max_price FROM watch WHERE user_id = ? ORDER BY id", (user_id,))
    return [_watch(r) for r in rows]


async def everything(db: Database) -> list[Watch]:
    return [_watch(r) for r in await db.fetchall("SELECT id, user_id, query, max_price FROM watch ORDER BY id")]


async def known_deals(db: Database, watch_ids: Iterable[int]) -> set[tuple[int, str]]:
    """O kterých akcích už lidé ví: {(watch_id, klíč akce)} (klíč = shops.watching.hit_key)."""
    ids = list(watch_ids)
    if not ids:
        return set()
    marks = ",".join("?" * len(ids))
    rows = await db.fetchall(f"SELECT watch_id, deal_id FROM watch_hit WHERE watch_id IN ({marks})", ids)
    return {(r["watch_id"], r["deal_id"]) for r in rows}


async def mark_known(db: Database, hits: Iterable[tuple[int, str]], now: datetime) -> None:
    rows = [(w, d, now.strftime("%Y-%m-%d %H:%M")) for w, d in hits]
    if rows:
        async with db.transaction() as tx:
            await tx.executemany("INSERT OR IGNORE INTO watch_hit (watch_id, deal_id, notified_at) VALUES (?, ?, ?)", rows)
