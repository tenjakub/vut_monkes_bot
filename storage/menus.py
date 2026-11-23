"""Historie jídelníčků: co se kde který den vařilo a za kolik. Podklad pro hodnocení jídel a budoucí statistiky
(vývoj cen, co se vaří nejčastěji, kdy co dojde).

Ukládají se jen polévky a hlavní jídla (saláty, přílohy a dezerty z menz ne). Jeden řádek = jedno jídlo v jednom
podniku v jeden den, takže to je pár stovek řádků denně (~20 kB), za rok jednotky MB.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime

from lunch.models import Category, Menu, price_value
from lunch.service import TZ

from .db import Database

log = logging.getLogger(__name__)

NAME_LIMIT = 300  # delší názvy (s celým popisem) se zkrátí


@dataclass(frozen=True)
class StoredDish:
    id: int
    day: date
    place: str  # klíč podniku (Place.key)
    name: str
    category: str  # soup / main
    price: int | None  # Kč
    label: str | None
    economy: bool
    group: str | None


_UPSERT = """
INSERT INTO dish (day, place, name, category, price_kc, label, economy, dish_group, first_seen, last_seen)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (day, place, name) DO UPDATE SET
    category = excluded.category, price_kc = excluded.price_kc, label = excluded.label,
    economy = excluded.economy, dish_group = excluded.dish_group, last_seen = max(last_seen, excluded.last_seen)
"""


def _rows(menus: Iterable[Menu], now: datetime) -> list[tuple]:
    day = now.date()
    rows: dict[tuple[str, str], tuple] = {}  # (podnik, název) -> řádek, stejné jídlo dvakrát jen jednou
    for menu in menus:
        fetched = menu.fetched_at.astimezone(now.tzinfo) if menu.fetched_at and now.tzinfo else menu.fetched_at
        if menu.error or (fetched and fetched.date() != day):
            continue
        seen = (fetched or now).strftime("%H:%M")  # kdy bylo jídlo opravdu na webu, ne kdy se ukládá
        for d in menu.dishes:
            if d.category is Category.SIDE or not d.name:
                continue
            name = d.name[:NAME_LIMIT]
            price = price_value(d.price)
            rows[(menu.place.key, name)] = (
                day.isoformat(), menu.place.key, name, d.category.value,
                round(price) if price is not None else None, d.label, int(d.economy), d.group, seen, seen,
            )
    return list(rows.values())


async def record(db: Database, menus: Iterable[Menu], now: datetime) -> int:
    """Uloží (nebo aktualizuje) dnešní jídla. U každého se pamatuje, kdy bylo v menu poprvé a naposledy
    (čas stažení stránky), takže se později dá zjistit, kdy v menze co došlo. Vrací počet uložených jídel."""
    rows = _rows(menus, now)
    if rows:
        async with db.transaction() as tx:
            await tx.executemany(_UPSERT, rows)
    return len(rows)


async def remember(db: Database | None, menus: Iterable[Menu], now: datetime | None = None) -> None:
    """Pro obnovu na pozadí: uloží právě stažená jídla, když databáze běží. Chyba databáze nic neshodí."""
    if db is None or not db.is_open:
        return
    now = now or datetime.now(TZ)
    try:
        await record(db, menus, now)
    except Exception:
        log.exception("Uložení jídelníčků do databáze selhalo")


def _dish(row) -> StoredDish:
    return StoredDish(
        row["id"], date.fromisoformat(row["day"]), row["place"], row["name"], row["category"],
        row["price_kc"], row["label"], bool(row["economy"]), row["dish_group"],
    )


_COLUMNS = "id, day, place, name, category, price_kc, label, economy, dish_group"


async def for_day(db: Database, day: date, places: Iterable[str]) -> list[StoredDish]:
    places = list(places)
    if not places:
        return []
    marks = ",".join("?" * len(places))
    rows = await db.fetchall(
        f"SELECT {_COLUMNS} FROM dish WHERE day = ? AND place IN ({marks}) ORDER BY id",
        (day.isoformat(), *places),
    )
    return [_dish(r) for r in rows]


async def get(db: Database, dish_id: int) -> StoredDish | None:
    row = await db.fetchone(f"SELECT {_COLUMNS} FROM dish WHERE id = ?", (dish_id,))
    return _dish(row) if row else None
