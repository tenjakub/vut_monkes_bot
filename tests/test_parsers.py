"""Testy parserů nad uloženými stránkami (stažené 20. 11. 2026)."""

from datetime import date
from pathlib import Path

import pytest

from lunch import kam, lastrada, menicka, service, sesamo, ukarla
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


def test_ukarla_weekend():
    """U Karla z vlastního webu (stažený 21. 11. 2026) – menu i o víkendu, které na menicka.cz chybí."""
    menu = ukarla.parse(read("ukarla.html"), place("ukarla"), date(2026, 11, 21))
    assert [d.name for d in menu.soups] == ["Kuřecí vývar s trhaným masem a nudlemi"]
    mains = menu.mains
    assert [(d.label, d.price) for d in mains] == [("1", "194 Kč"), ("2", "214 Kč"), ("3", "204 Kč")]
    assert mains[0].name == "Smažený kuřecí řízek, vařené brambory s máslem a pažitkou, okurkový salátek"


def test_ukarla_weekday_and_missing_day():
    menu = ukarla.parse(read("ukarla.html"), place("ukarla"), date(2026, 11, 23))
    assert len(menu.mains) == 4 and menu.mains[2].name.startswith("BBQ Burger (")
    assert menu.soups[0].name == "Fazolová s brambory a kořenovou zeleninou"
    empty = ukarla.parse(read("ukarla.html"), place("ukarla"), date(2026, 12, 5))
    assert empty.dishes == [] and empty.note


def test_restaurants_share_no_menu_text():
    """Den bez menu hlásí všechny restaurace stejně jako menicka.cz."""
    from lunch.models import NO_MENU

    assert menicka.parse(read("menicka_u3opic.html"), place("u3opic"), date(2026, 11, 22)).note == NO_MENU
    assert lastrada.parse(read("lastrada.html"), place("lastrada"), date(2026, 11, 22)).note == NO_MENU
    assert ukarla.parse(read("ukarla.html"), place("ukarla"), date(2026, 12, 5)).note == NO_MENU


def test_sesamo():
    """Sesamo (menu_cz.html stažené 21. 11. 2026): dny jako rozsahy, polévky bez čísla, víkendové menu."""
    weekend = sesamo.parse(read("sesamo.html"), place("sesamo"), date(2026, 11, 22))
    assert [(d.name, d.price) for d in weekend.soups] == [("Rajská polévka", "50 Kč"), ("Boršč", "70 Kč")]
    assert [d.label for d in weekend.mains] == ["a", "b", "c", "d", "5", "6", "7", "8"]
    assert weekend.mains[1].name == "Gnocchi se 4 sýry a klobásou" and weekend.mains[1].price == "250 Kč"
    tuesday = sesamo.parse(read("sesamo.html"), place("sesamo"), date(2026, 11, 17))
    assert len(tuesday.mains) == 10 and tuesday.soups[0].name == "Houbová polevka"
    # aperitivo (večerní akce ve čtvrtek) se mezi jídla nepočítá
    thursday = sesamo.parse(read("sesamo.html"), place("sesamo"), date(2026, 11, 19))
    assert not any("drink" in d.name for d in thursday.dishes)
    from lunch.models import NO_MENU

    assert sesamo.parse(read("sesamo.html"), place("sesamo"), date(2026, 11, 23)).note == NO_MENU


def test_sesamo_groups_and_pizza_ingredients():
    """Pizzy a těstoviny jsou ve skupinách, přísady pizz z velkého menu (hlavní stránka, PIZZAS v JS)."""
    menu = sesamo.parse(read("sesamo.html"), place("sesamo"), date(2026, 11, 16))
    menu = sesamo.add_descriptions(menu, read("sesamo_index.html"))
    groups = {d.name: d.group for d in menu.mains}
    assert groups["Penne se smetanou a šunkou"] == sesamo.PASTA and groups["Lasagne Bolognese"] == sesamo.PASTA
    assert groups["Pizza šunka"] == sesamo.PIZZA and groups["Gurmánská pizza se špekem a mascarpone"] == sesamo.PIZZA
    assert groups["Vepřová panenka s bramborovou kaší"] is None
    desc = {d.name: d.description for d in menu.mains}
    assert desc["Pizza šunka"] == "Rajčatová omáčka, sýr mozzarella, šunka"
    assert desc["Pizza diavola"] == "Rajčatová omáčka, sýr mozzarella, pikantní salám, chilli"  # = salami diavola
    assert desc["Pizza chef"] == ""  # ve velkém menu není
    # bez seznamu pizz (změna webu) zůstane menu, jak bylo
    plain = sesamo.parse(read("sesamo.html"), place("sesamo"), date(2026, 11, 16))
    assert sesamo.add_descriptions(plain, "<html></html>").dishes == plain.dishes


def test_extra_page_failure_keeps_menu():
    import asyncio

    r = next(r for r in service.RESTAURANTS if r.place.key == "sesamo")
    menu = sesamo.parse(read("sesamo.html"), r.place, date(2026, 11, 16))

    class BrokenFetcher:
        async def get(self, url, ttl, force=False):
            raise OSError("web nejede")

    assert asyncio.run(service._with_extra(BrokenFetcher(), r, menu)) is menu


def test_restaurant_fields_put_groups_below_grid():
    from cogs import restaurace

    menu = sesamo.add_descriptions(
        sesamo.parse(read("sesamo.html"), place("sesamo"), date(2026, 11, 16)), read("sesamo_index.html")
    )
    fields = restaurace.restaurant_fields(menu)
    names = [f.name for f in fields]
    assert names[0] == "🥣 Polévky" and names[-2:] == ["🍝 Těstoviny", "🍕 Pizza"]
    pizza = fields[-1].value.splitlines()
    assert pizza[1] == "• 8. **Šunka** · 229 Kč – rajčatová omáčka, sýr mozzarella, šunka"
    assert pizza[0] == "• 7. **Chef** · 199 Kč"
    assert not any(f.inline for f in fields[-2:])
