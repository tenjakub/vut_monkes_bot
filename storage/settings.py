"""Nastavení serverů (/nastaveni, jen pro adminy). Hodnoty jsou v paměti (`_cache`), ať je jde číst i při
vykreslování zpráv bez čekání na databázi: načtou se při startu (`load`) a mění se jen přes `put`.

Bez uložené hodnoty (nebo bez databáze) platí výchozí, takže se nic nemění, dokud admin něco nenastaví.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .db import Database

EVENT_MIN_PEOPLE = "udalost_lidi"  # kolik lidí musí jít na /na-pivo, aby bot založil událost; "0" = vypnuto
DEFAULT_EVENT_MIN_PEOPLE = 3
DEFAULTS: dict[str, str] = {EVENT_MIN_PEOPLE: str(DEFAULT_EVENT_MIN_PEOPLE)}

_cache: dict[int, dict[str, str]] = {}


@dataclass(frozen=True)
class Change:
    value: str
    updated_by: int
    updated_at: str


async def load(db: Database) -> None:
    rows = await db.fetchall("SELECT guild_id, key, value FROM guild_setting")
    _cache.clear()
    for r in rows:
        _cache.setdefault(r["guild_id"], {})[r["key"]] = r["value"]


def get(guild_id: int | None, key: str) -> str:
    if guild_id is None:
        return DEFAULTS[key]
    return _cache.get(guild_id, {}).get(key, DEFAULTS[key])


async def put(db: Database, guild_id: int, key: str, value: str, user_id: int, now: datetime) -> None:
    if key not in DEFAULTS:
        raise KeyError(key)
    await db.execute(
        "INSERT INTO guild_setting (guild_id, key, value, updated_by, updated_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (guild_id, key) DO UPDATE SET value = excluded.value, updated_by = excluded.updated_by, "
        "updated_at = excluded.updated_at",
        (guild_id, key, value, user_id, now.strftime("%Y-%m-%d %H:%M")),
    )
    _cache.setdefault(guild_id, {})[key] = value


async def last_change(db: Database, guild_id: int, key: str) -> Change | None:
    row = await db.fetchone(
        "SELECT value, updated_by, updated_at FROM guild_setting WHERE guild_id = ? AND key = ?", (guild_id, key)
    )
    return Change(row["value"], row["updated_by"], row["updated_at"]) if row else None


def event_min_people(guild_id: int | None) -> int | None:
    """Od kolika lidí zakládat událost z /na-pivo, None = vůbec (vypnuto, nebo DM, kde žádný server není)."""
    if guild_id is None:
        return None
    try:
        value = int(get(guild_id, EVENT_MIN_PEOPLE))
    except ValueError:
        value = DEFAULT_EVENT_MIN_PEOPLE
    return value if value > 0 else None
