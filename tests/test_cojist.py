"""/co-jist: výběr kandidátů a vzhled doporučení (bez sítě, s falešnými jídelníčky)."""

import asyncio
from types import SimpleNamespace

from cogs import cojist
from lunch import service
from lunch.models import Category, Dish, Menu, Place

MENZA = Place("sp", "Menza Starý pivovar", "https://example.invalid/sp", "🍺")
RESTAURANT = Place("ls", "La Strada", "https://example.invalid/ls", "🍝")


def _fake(monkeypatch):
    menza = Menu(MENZA, [
        Dish("Polévka", "18 Kč", Category.SOUP),
        Dish("Kuře s rýží", "94 Kč", label="E4", economy=True),
        Dish("Svíčková", "120 Kč"),
    ], hours="11:00–14:30")
    restaurant = Menu(RESTAURANT, [
        Dish("Pizza dle výběru", "175 Kč", label="3", options=[("Fresca", "pomodoro, rukola")]),
    ])

    async def menza_menus(fetcher, group, force=False):
        return [menza]

    async def restaurant_menus(fetcher, force=False):
        return [restaurant]

    monkeypatch.setattr(service, "menza_menus", menza_menus)
    monkeypatch.setattr(service, "restaurant_menus", restaurant_menus)


def test_candidates_by_scope(monkeypatch):
    _fake(monkeypatch)
    names = lambda scope: sorted(p.dish.name for p in asyncio.run(cojist.candidates(None, scope)))
    assert names("vse") == ["Kuře s rýží", "Pizza dle výběru", "Svíčková"]  # bez polévek
    assert names("menzy") == ["Kuře s rýží", "Svíčková"]
    assert names("economy") == ["Kuře s rýží"]
    assert names("restaurace") == ["Pizza dle výběru"]


def test_pick_embed(monkeypatch):
    _fake(monkeypatch)
    picks = {p.dish.name: p for p in asyncio.run(cojist.candidates(None, "vse"))}
    eco = cojist.pick_embed(picks["Kuře s rýží"])
    assert eco.title.endswith("Economy 4: Kuře s rýží")
    assert [(f.name, f.value) for f in eco.fields] == [
        ("📍 Kde", "🍺 Menza Starý pivovar"), ("💸 Cena", "94 Kč (student)"), ("🕐 Otevřeno", "11:00–14:30"),
    ]
    pizza = cojist.pick_embed(picks["Pizza dle výběru"])
    assert pizza.title == "🍕 Pizza Fresca (pomodoro, rukola)"


def test_nothing_today(monkeypatch):
    _fake(monkeypatch)
    async def empty(fetcher, *a, **kw):
        return []
    monkeypatch.setattr(service, "restaurant_menus", empty)
    content, embeds, view = asyncio.run(cojist.build_message(SimpleNamespace(fetcher=None), "restaurace"))
    assert embeds == [] and "nic není" in content
    ids = [getattr(getattr(i, "item", i), "custom_id", None) for i in view.children]
    assert len(ids) == len(set(ids))
