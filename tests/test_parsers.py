"""Testy parserů nad uloženými stránkami (stažené 20. 11. 2026)."""

from datetime import date
from pathlib import Path

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
    assert "Fresca" in menu.mains[2].name


def test_lastrada_holiday():
    menu = lastrada.parse(read("lastrada.html"), place("lastrada"), date(2026, 11, 17))
    assert menu.dishes == []
    assert "svátek" in menu.note.lower()


def test_lastrada_weekend():
    menu = lastrada.parse(read("lastrada.html"), place("lastrada"), date(2026, 11, 21))
    assert menu.dishes == [] and menu.note
