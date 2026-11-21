"""Scraper denního menu SESAMO Bakery Pizza (Purkyňova 97c, https://sesamobrno.cz/#menu).

Menu je na webu v iframu ze souboru `menu_cz.html`: týden jako `.section` s nadpisem dne nebo rozsahu dnů
(„Pondělí 16.11.2026“, „Sobota 21.11.2026 – Neděle 22.11.2026“) a položkami `.item` (`.num`, `.text`, `.price`).
Položky bez čísla jsou polévky. Sekce `.aperitivo` (večerní akce) se přeskakuje.

Pizzy a těstoviny dostanou skupinu (v /restaurace se vypíšou pod mřížkou jako pizza dne u La Strady).
Přísady pizz jsou ve velkém menu na hlavní stránce, v JavaScriptu `const PIZZAS=[[název, cena, popis, obrázek], …]`
(`add_descriptions`). Těstoviny tam nejsou, ty mají přísady přímo v názvu.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import replace
from datetime import date

from bs4 import BeautifulSoup

from .models import NO_MENU, Category, Dish, Menu, Place, norm

PAGE_URL = "https://sesamobrno.cz/#menu"  # pro lidi
URL = "https://sesamobrno.cz/menu_cz.html"  # samotné menu
BIG_MENU_URL = "https://sesamobrno.cz/"  # velké menu s přísadami pizz

PIZZA, PASTA = "Pizza", "Těstoviny"
_PIZZA_WORDS = ("pizza", "calzone")
_PASTA_WORDS = ("těstovin", "penne", "špaget", "spaghetti", "lasagne", "gnocchi", "tagliatelle", "ravioli",
                "fusilli", "rigatoni", "linguine", "carbonara", "pappardelle", "farfalle", "tortellini")
_PIZZAS_RE = re.compile(r"const\s+PIZZAS\s*=\s*(\[.*?\]);", re.S)

_DATE_RE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")


def _days(heading: str) -> tuple[date, date] | None:
    """'Sobota 21.11.2026 – Neděle 22.11.2026' -> (21. 11., 22. 11.); jeden den -> (den, den)."""
    found = [date(int(y), int(m), int(d)) for d, m, y in _DATE_RE.findall(heading)]
    return (found[0], found[-1]) if found else None


def group_of(name: str) -> str | None:
    low = name.lower()
    if any(w in low for w in _PIZZA_WORDS):
        return PIZZA
    if any(w in low for w in _PASTA_WORDS):
        return PASTA
    return None


def _key(name: str) -> tuple[str, ...]:
    """'Pizza salami diavola' -> ('salami', 'diavola'): bez diakritiky, bez slova pizza."""
    plain = unicodedata.normalize("NFKD", name.lower()).encode("ascii", "ignore").decode()
    return tuple(w for w in re.findall(r"[a-z0-9]+", plain) if w != "pizza")


def big_menu(html: str) -> dict[tuple[str, ...], str]:
    """Pizzy z velkého menu: klíč názvu -> přísady."""
    m = _PIZZAS_RE.search(html)
    if not m:
        return {}
    return {_key(row[0]): norm(row[2]) for row in json.loads(m.group(1)) if len(row) >= 3 and row[2]}


def description_for(name: str, pizzas: dict[tuple[str, ...], str]) -> str:
    """Přísady pizzy z denního menu. Denní menu název zkracuje („Pizza diavola“ = „Pizza salami diavola“),
    proto stačí, když všechna slova sedí do jediné pizzy z velkého menu."""
    key = _key(name)
    if not key:
        return ""
    if key in pizzas:
        return pizzas[key]
    matches = [desc for k, desc in pizzas.items() if set(key) <= set(k)]
    return matches[0] if len(matches) == 1 else ""


def add_descriptions(menu: Menu, html: str) -> Menu:
    pizzas = big_menu(html)
    dishes = [
        replace(d, description=description_for(d.name, pizzas)) if d.group == PIZZA and not d.description else d
        for d in menu.dishes
    ]
    return replace(menu, dishes=dishes)


def parse(html: str, place: Place, today: date) -> Menu:
    soup = BeautifulSoup(html, "html.parser")
    for section in soup.select("div.section"):
        heading = section.find("h2")
        days = _days(heading.get_text(" ") if heading else "")
        if not days or not (days[0] <= today <= days[1]):
            continue
        dishes = []
        for item in section.select(".item"):
            text_el, price_el, num_el = item.select_one(".text"), item.select_one(".price"), item.select_one(".num")
            name = norm(text_el.get_text(" ")) if text_el else ""
            if not name:
                continue
            price = norm(price_el.get_text()) if price_el else None
            if num_el is None:  # bez čísla = polévka ("houbová polevka", "Boršč")
                dishes.append(Dish(name=name[:1].upper() + name[1:], price=price, category=Category.SOUP))
            else:
                label = norm(num_el.get_text()).rstrip(".") or None
                dishes.append(Dish(name=name, price=price, label=label, group=group_of(name)))
        if dishes:
            return Menu(place, dishes=dishes)
    return Menu(place, note=NO_MENU)
