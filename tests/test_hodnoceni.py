"""⭐ Hodnocení jídel: ukládání, souhrn ve výpisu a průchod tlačítky (výběr → 👍/😐/👎 → zrušit)."""

import asyncio
from datetime import datetime
from types import SimpleNamespace

from cogs import hodnoceni, menza
from lunch import kam, service
from lunch.models import Category, Dish, Menu
from storage import Database, ratings
from storage import menus as stored_menus
from tests.fakes import Interaction, memory_db, with_values
from utils import interactions

NOW = datetime(2026, 11, 23, 11, 30, tzinfo=service.TZ)


def run(coro):
    return asyncio.run(coro)


def _menus(fetched: datetime = NOW) -> list[Menu]:
    kolejni = Menu(kam.MENZY["kolejni"], [
        Dish("Polévka rajská", "15 Kč", Category.SOUP),
        Dish("Economy 1: Kuře s rýží", "75 Kč", label="E1", economy=True),
        Dish("Svíčková", "110 Kč"),
    ], fetched_at=fetched)
    mozzarella = Menu(kam.MENZY["mozzarella"], [Dish("Pizza Margherita", "99 Kč")], fetched_at=fetched)
    pivovar = Menu(kam.MENZY["stary_pivovar"], [], fetched_at=fetched)
    return [kolejni, mozzarella, pivovar]


def _patch(monkeypatch):
    menus = _menus()

    async def menza_menus(fetcher, group, force=False):
        return menus

    monkeypatch.setattr(service, "menza_menus", menza_menus)
    monkeypatch.setattr(service, "today", lambda: NOW.date())
    monkeypatch.setattr(stored_menus, "datetime", SimpleNamespace(now=lambda tz=None: NOW))


def test_summary_counts_across_days():
    async def go():
        async with memory_db() as db:
            await stored_menus.record(db, _menus(), NOW)
            tomorrow = datetime(2026, 11, 24, 11, 0, tzinfo=service.TZ)
            await stored_menus.record(db, _menus(tomorrow), tomorrow)
            dishes = [d for d in await stored_menus.for_day(db, NOW.date(), ["kolejni"]) if d.name == "Svíčková"]
            again = [d for d in await stored_menus.for_day(db, tomorrow.date(), ["kolejni"]) if d.name == "Svíčková"]
            await ratings.rate(db, dishes[0].id, 1, ratings.GOOD, NOW)
            await ratings.rate(db, dishes[0].id, 2, ratings.BAD, NOW)
            await ratings.rate(db, dishes[0].id, 2, ratings.OK, NOW)  # přehodnotil
            await ratings.rate(db, again[0].id, 3, ratings.GOOD, tomorrow)
            return await ratings.summaries(db, [("kolejni", "Svíčková"), ("kolejni", "Polévka rajská")])

    assert run(go()) == {("kolejni", "Svíčková"): ratings.Summary(good=2, ok=1, bad=0)}
    assert ratings.Summary(2, 1, 0).text() == "👍 2 · 😐 1"


def test_rating_flow_and_note_in_menu(monkeypatch):
    _patch(monkeypatch)

    async def go():
        async with memory_db() as db:
            client = SimpleNamespace(db=db, fetcher=None)
            # 1. ⭐ Ohodnotit → výběr jídla (hlavní jídla první, polévka na konci)
            click = Interaction(client, user_id=7)
            await hodnoceni.RateButton("ppv").callback(click)
            select = click.followup.sent[0]["view"].children[0].item
            labels = [o.label for o in select.options]
            # 2. výběr jídla → tři tlačítka
            pick = Interaction(client, user_id=7)
            svickova = next(o.value for o in select.options if o.label == "Svíčková")
            await with_values(hodnoceni.DishSelect(), svickova).callback(pick)
            buttons = [b.item.custom_id for b in pick.response.calls[0][1]["view"].children]
            # 3. 👍 → uloženo, tlačítko Zrušit
            vote = Interaction(client, user_id=7)
            await hodnoceni.VoteButton(int(svickova), "g").callback(vote)
            saved = vote.response.calls[0][1]
            _, embeds, _ = await menza.build_message(client, "ppv", menza.MODE_ALL)
            # 4. ↩️ Zrušit
            undo = Interaction(client, user_id=7)
            await hodnoceni.UndoButton(int(svickova)).callback(undo)
            left = await ratings.summaries(client.db, [("kolejni", "Svíčková")])
            return labels, buttons, saved, embeds, undo.response.calls[0][1], left, svickova

    labels, buttons, saved, embeds, undone, left, dish_id = run(go())
    assert labels == ["Economy 1: Kuře s rýží", "Svíčková", "Pizza Margherita", "Polévka rajská"]
    assert buttons == [f"znamka:h:{dish_id}:{s}" for s in "gob"]
    assert saved["content"].startswith("✅ Uloženo: 👍 **Dobré** – Svíčková")
    assert saved["view"].children[0].item.custom_id == f"znamka:z:{dish_id}"
    card = next(f for f in embeds[0].fields if "Svíčková" in f.value)
    assert card.value.endswith("\n-# 👍 1")
    assert undone["content"].startswith("↩️ Hodnocení zrušeno.") and left == {}


def test_stale_and_missing_database(monkeypatch):
    _patch(monkeypatch)

    async def go():
        async with memory_db() as db:
            client = SimpleNamespace(db=db, fetcher=None)
            stale = Interaction(client)
            await hodnoceni.VoteButton(999, "g").callback(stale)
            unknown = Interaction(client)
            await hodnoceni.RateButton("neexistuje").callback(unknown)
        offline = Interaction(SimpleNamespace(db=Database(":memory:"), fetcher=None))
        await hodnoceni.RateButton("ppv").callback(offline)
        return stale.last(), unknown.last(), offline.last()

    stale, unknown, offline = run(go())
    assert stale["content"] == hodnoceni.STALE and unknown["content"] == hodnoceni.STALE
    assert offline["content"] == interactions.UNAVAILABLE


def test_sold_out_dish_still_offered(monkeypatch):
    """Jídlo, které menza už smazala (vyprodané), jde ohodnotit i odpoledne."""
    _patch(monkeypatch)

    async def go():
        async with memory_db() as db:
            morning = _menus()
            morning[0].dishes.append(Dish("Economy 3: Rizoto", "70 Kč", label="E3", economy=True))
            await stored_menus.record(db, morning, NOW)
            click = Interaction(SimpleNamespace(db=db, fetcher=None), user_id=7)
            await hodnoceni.RateButton("ppv").callback(click)
            return {o.label: o.description for o in click.followup.sent[0]["view"].children[0].item.options}

    options = run(go())
    assert options["Economy 3: Rizoto"].endswith("· došlo")
    assert not options["Svíčková"].endswith("došlo")


def test_too_many_dishes_pick_place_first(monkeypatch):
    """/menzy: víc než 25 jídel → napřed výběr menzy, pak jídla jen z ní (a výběr menzy zůstane nahoře)."""
    menus = _menus()
    menus[0].dishes += [Dish(f"Jídlo {i}", "90 Kč") for i in range(20)]
    menus[1].dishes += [Dish(f"Pizza {i}", "99 Kč") for i in range(10)]

    async def menza_menus(fetcher, group, force=False):
        return menus

    monkeypatch.setattr(service, "menza_menus", menza_menus)
    monkeypatch.setattr(service, "today", lambda: NOW.date())
    monkeypatch.setattr(stored_menus, "datetime", SimpleNamespace(now=lambda tz=None: NOW))

    async def go():
        async with memory_db() as db:
            client = SimpleNamespace(db=db, fetcher=None)
            click = Interaction(client, user_id=7)
            await hodnoceni.RateButton("vse").callback(click)
            first = click.followup.sent[0]
            pick = Interaction(client, user_id=7)
            await with_values(hodnoceni.PlaceSelect("vse"), "mozzarella").callback(pick)
            return first, pick.response.calls[0][1]

    first, picked = run(go())
    assert first["content"].startswith("⭐ **Kde jsi jedl(a)?**")
    (places,) = first["view"].children
    assert places.item.custom_id == "znamka:m:vse"
    assert [(o.value, o.description) for o in places.item.options] == [
        ("kolejni", "23 jídel"), ("mozzarella", "11 jídel"),
    ]
    places, dishes = picked["view"].children
    assert [o.default for o in places.item.options] == [False, True]
    assert len(dishes.item.options) == 11
    assert {o.label for o in dishes.item.options} == {"Pizza Margherita", *(f"Pizza {i}" for i in range(10))}
