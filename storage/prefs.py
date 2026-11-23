"""Nastavení jednotlivých lidí (tabulka `user_setting`). Zatím jen výchozí koleje (/koleje).

Bez uloženého nastavení se všechno chová jako dřív; „nerozhodnuto“ řádek smaže, takže se o člověku nic nedrží.
"""

from __future__ import annotations

import logging

from .db import Database

log = logging.getLogger(__name__)

DORM = "koleje"
DORMS = ("ppv", "purkyne")  # klíče oblastí /mhd a /kola (transit AREAS „vse“ = PPV, bikes AREAS „ppv“)


async def get(db: Database, user_id: int, key: str) -> str | None:
    row = await db.fetchone("SELECT value FROM user_setting WHERE user_id = ? AND key = ?", (user_id, key))
    return row["value"] if row else None


async def put(db: Database, user_id: int, key: str, value: str | None) -> None:
    """Uloží nastavení, `None` ho smaže (= výchozí chování)."""
    if value is None:
        await db.execute("DELETE FROM user_setting WHERE user_id = ? AND key = ?", (user_id, key))
    else:
        await db.execute(
            "INSERT INTO user_setting (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT (user_id, key) DO UPDATE SET value = excluded.value",
            (user_id, key, value),
        )


async def dorm(db: Database | None, user_id: int) -> str | None:
    """Výchozí koleje člověka („ppv“ / „purkyne“), nebo None (nerozhodnuto, nebo databáze neběží)."""
    if db is None or not db.is_open:
        return None
    try:
        value = await get(db, user_id, DORM)
    except Exception:
        log.exception("Načtení výchozích kolejí selhalo")
        return None
    return value if value in DORMS else None
