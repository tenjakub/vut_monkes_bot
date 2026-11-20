"""Testy parserů nad uloženými stránkami (stažené 20. 11. 2026)."""

from datetime import date
from pathlib import Path

import pytest

from lunch import kam, lastrada, menicka, service
from lunch.models import Category

FIX = Path(__file__).parent / "fixtures"
DAY = date(2026, 11, 20)


def read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def place(key: str):
    return next(r.place for r in service.RESTAURANTS if r.place.key == key)


def test_kam_economy():
    menu = kam.parse(read("kam_stary_pivovar.html"), kam.MENZY["stary_pivovar"])
    eco = menu.economy
    assert [d.label for d in eco] == ["E1", "E2", "E3", "E4"]
    assert eco[0].name == "Závitek kuřecí se šunkou a žampiony, Hranolky"
    assert eco[0].price == "118 Kč"
    assert len(menu.soups) == 2
    # saláty a přílohy jsou "ostatní"
    assert any(d.category is Category.SIDE and d.name.startswith("Salát") for d in menu.dishes)
    assert not any(d.name.startswith("Salát") for d in menu.mains)


def test_kam_only_salads():
    menu = kam.parse(read("kam_kolejni.html"), kam.MENZY["kolejni"])
    assert menu.economy == []
    assert menu.mains == []
    assert menu.error is None


def test_kam_closed():
    menu = kam.parse(read("kam_closed.html"), kam.MENZY["kolejni"])
    assert menu.dishes == []
    assert menu.note


def test_menicka_u3opic():
    menu = menicka.parse(read("menicka_u3opic.html"), place("u3opic"), DAY)
    assert menu.soups and "Frankfurtská" in menu.soups[0].name
    assert menu.mains[0].label == "1"
    assert menu.mains[0].price == "159 Kč"
    assert menu.hours == "11:00 – 14:00"


def test_menicka_other_day_is_empty():
    menu = menicka.parse(read("menicka_padagali.html"), place("padagali"), date(2026, 11, 21))
    assert menu.dishes == []
    assert menu.note


def test_menicka_padagali():
    menu = menicka.parse(read("menicka_padagali.html"), place("padagali"), DAY)
    assert len(menu.mains) == 5
    assert menu.mains[0].name.startswith("CHICKEN MADRAS")


def test_lastrada_today():
    menu = lastrada.parse(read("lastrada.html"), place("lastrada"), DAY)
    assert menu.soups[0].name.startswith("Dýňová polévka")
    assert [d.label for d in menu.mains] == ["1", "2", "3", "4"]
    assert menu.mains[0].price == "165 Kč"
    assert menu.mains[3].price == "175 Kč"
    pizza = menu.mains[2]
    assert pizza.label == "3" and pizza.price == "175 Kč"
    assert pizza.options[0] == ("Fresca", "pomodoro, mozzarella, balkánský sýr, rukola")
    assert pizza.options[3] == ("Vegan La Strada 🌱", "vegan smetana, vegan mozzarella, sušená rajčata, olivy")
    assert [d.options for d in menu.mains if d is not pizza] == [[], [], []]


def test_lastrada_holiday():
    menu = lastrada.parse(read("lastrada.html"), place("lastrada"), date(2026, 11, 17))
    assert menu.dishes == []
    assert "svátek" in menu.note.lower()


def test_lastrada_weekend():
    menu = lastrada.parse(read("lastrada.html"), place("lastrada"), date(2026, 11, 21))
    assert menu.dishes == [] and menu.note


def test_menicka_strips_allergens():
    menu = menicka.parse(read("menicka_portoriko.html"), place("portoriko"), DAY)
    assert menu.soups[0].name == "Vývar s kořenovou zeleninou a nudlemi"
    assert menu.mains[0].name == "Trhané kuře na paprice s kolínky a nebo houskovým knedlíkem"
    assert len(menu.mains) == 5


@pytest.mark.parametrize(
    ("day", "stary_pivovar", "purkynova"),
    [
        (date(2026, 11, 19), "11:00–14:30", "11:00–14:30, 17:00–20:00"),  # čtvrtek
        (date(2026, 11, 20), "11:00–14:00", "11:00–14:00"),  # pátek
        (date(2026, 11, 21), "zavřeno", "zavřeno"),  # sobota
        (date(2026, 11, 17), "zavřeno", "zavřeno"),  # státní svátek = jako víkend
        (date(2026, 11, 16), "11:00–14:00", "11:00–14:00"),  # den před svátkem = jako pátek
    ],
)
def test_kam_opening_hours(day, stary_pivovar, purkynova):
    hours = kam.parse_hours(read("kam_otdo.html"), day)
    assert hours[kam.MENZY["stary_pivovar"].provoz] == stary_pivovar
    assert hours[kam.MENZY["purkynova"].provoz] == purkynova


def test_cz_holidays_include_easter():
    holidays = kam.cz_holidays(2026)
    assert date(2026, 4, 3) in holidays and date(2026, 4, 6) in holidays  # Velký pátek, Velikonoční pondělí
    assert date(2026, 11, 17) in holidays and len(holidays) == 13


class _FakeFetcher:
    """Vrací uložené stránky místo stahování: přehled otevíracích dob + jídelníček Starého pivovaru."""

    async def get(self, url, ttl, force=False):
        if url == kam.OVERVIEW_URL:
            return read("kam_otdo.html"), 0.0
        if url == kam.MENZY["stary_pivovar"].url:
            return read("kam_stary_pivovar.html"), 0.0
        raise ConnectionError(url)


def test_menza_menus_attach_hours_and_survive_errors(monkeypatch):
    import asyncio

    monkeypatch.setattr(service, "today", lambda: date(2026, 11, 19))
    menus = asyncio.run(service.menza_menus(_FakeFetcher(), "ppv"))
    by_key = {m.place.key: m for m in menus}
    sp = by_key["stary_pivovar"]
    assert sp.error is None and len(sp.economy) == 4
    assert (sp.hours_label, sp.hours) == ("🕐 Dnes", "11:00–14:30")
    # Kolejní se "nestáhla" -> chyba jen u ní, otevírací doba se i tak ukáže
    assert by_key["kolejni"].error and by_key["kolejni"].hours == "11:00–14:30"


def test_lastrada_pizza_rendered_separately():
    from cogs.restaurace import restaurant_fields

    menu = lastrada.parse(read("lastrada.html"), place("lastrada"), DAY)
    fields = restaurant_fields(menu)
    assert [f.inline for f in fields] == [False, True, True, True, False]  # polévka, mřížka 1/2/4, pizza
    pizza = fields[-1]
    assert pizza.name.startswith("🍕 3 · 175 Kč · Pizza dle výběru")
    assert pizza.value.split("\n")[0] == "• **Fresca** – pomodoro, mozzarella, balkánský sýr, rukola"


def test_menus_cached_until_midnight_outside_lunch_hours():
    from datetime import datetime

    from lunch import service

    def at(h, m=0):
        return datetime(2026, 11, 20, h, m, tzinfo=service.TZ)

    assert service.effective_ttl(900, at(12)) == 900  # přes den běžné TTL, obnova běží na pozadí
    assert service.effective_ttl(900, at(21, 30)) == 21.5 * 3600  # večer platí, co se dnes stáhlo
    assert service.effective_ttl(900, at(0, 5)) == 900  # po půlnoci se stáhne jednou znovu
    assert service.effective_ttl(900, at(3)) == 3 * 3600
