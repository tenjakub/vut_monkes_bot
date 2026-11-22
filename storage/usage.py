"""Statistiky commandů (testovací využití databáze): kolikrát se který command použil. Jen počty, žádná ID lidí."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .db import Database


@dataclass(frozen=True)
class Usage:
    command: str
    count: int


async def record(db: Database, command: str, day: date) -> None:
    await db.execute(
        "INSERT INTO command_usage (day, command, count) VALUES (?, ?, 1) "
        "ON CONFLICT (day, command) DO UPDATE SET count = count + 1",
        (day.isoformat(), command),
    )


async def top(db: Database, since: date | None = None) -> list[Usage]:
    """Commandy podle počtu použití od `since` (včetně), nebo za celou dobu."""
    rows = await db.fetchall(
        "SELECT command, SUM(count) AS total FROM command_usage WHERE day >= ? "
        "GROUP BY command ORDER BY total DESC, command",
        ((since or date.min).isoformat(),),
    )
    return [Usage(r["command"], r["total"]) for r in rows]


async def first_day(db: Database) -> date | None:
    """Odkdy se statistiky sbírají."""
    row = await db.fetchone("SELECT MIN(day) AS day FROM command_usage")
    return date.fromisoformat(row["day"]) if row and row["day"] else None
