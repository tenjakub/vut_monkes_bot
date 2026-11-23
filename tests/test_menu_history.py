"""Historie jídelníčků v databázi (storage/menus.py)."""

import asyncio
from datetime import date, datetime

from lunch.models import Category, Dish, Menu, Place
from lunch.service import TZ
from storage import Database, menus

KOLEJNI = Place("kolejni", "Menza Kolejní", "https://example.com/kolejni")
SESAMO = Place("sesamo", "Sesamo", "https://example.com/sesamo")
NOW = datetime(2026, 11, 23, 11, 30, tzinfo=TZ)


def run(coro):
    return asyncio.run(coro)


def _menza(fetched: datetime) -> Menu:
    return Menu(KOLEJNI, [
        Dish("Polévka rajská", "15 Kč", Category.SOUP),
        Dish("Economy 1: Kuře s rýží", "75 Kč", label="E1", economy=True),
        Dish("Svíčková", None),
        Dish("Okurkový salát", "20 Kč", Category.SIDE),  # přílohy a saláty se neukládají
    ], fetched_at=fetched)


def test_record_upserts_and_tracks_last_seen():
    async def go():
        db = Database(":memory:")
        await db.open()
        first = _menza(datetime(2026, 11, 23, 10, 0, tzinfo=TZ))
        later = _menza(datetime(2026, 11, 23, 12, 40, tzinfo=TZ))
        later.dishes = later.dishes[1:]  # polévka došla
        broken = Menu(SESAMO, error="Nepodařilo se načíst")
        assert await menus.record(db, [first, broken], NOW) == 3
        await menus.record(db, [later], NOW)
        stored = await menus.for_day(db, date(2026, 11, 23), ["kolejni", "sesamo"])
        seen = {r["name"]: (r["first_seen"], r["last_seen"]) for r in await db.fetchall("SELECT * FROM dish")}
        await db.close()
        return stored, seen

    stored, seen = run(go())
    assert [(d.name, d.category, d.price, d.economy) for d in stored] == [
        ("Polévka rajská", "soup", 15, False),
        ("Economy 1: Kuře s rýží", "main", 75, True),
        ("Svíčková", "main", None, False),
    ]
    assert seen["Polévka rajská"] == ("10:00", "10:00")  # kolem poledne už nebyla
    assert seen["Svíčková"] == ("10:00", "12:40")


def test_yesterdays_page_is_not_stored_as_today():
    async def go():
        db = Database(":memory:")
        await db.open()
        count = await menus.record(db, [_menza(datetime(2026, 11, 22, 23, 50, tzinfo=TZ))], NOW)
        await db.close()
        return count

    assert run(go()) == 0


def test_remember_without_database_does_nothing():
    run(menus.remember(None, [_menza(NOW)]))
    run(menus.remember(Database(":memory:"), [_menza(NOW)]))  # neotevřená
