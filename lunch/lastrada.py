"""Scraper poledního menu La Strada (https://lastrada-brno.cz/poledni-menu/).

Stránka obsahuje celý týden jako karty `.ls-card` s nadpisem "Pá 20.11. <polévka>"
a cenami v `.ls-pricing` ("MENU 1, 2 · 165 Kč").
"""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup

from .models import Category, Dish, Menu, Place, norm

URL = "https://lastrada-brno.cz/poledni-menu/"

_DAY_RE = re.compile(r"^\D*?(\d{1,2})\.\s*(\d{1,2})\.")
_ITEM_RE = re.compile(r"^(\d+[a-z]?)\)\s*(.*)$")
_PRICE_RE = re.compile(r"MENU\s*([\d,\s]+?)\s*\D*?(\d+)\s*Kč", re.IGNORECASE)


def _short_pizza(text: str) -> str:
    """'3a) Pizza Fresca (pomodoro, …)' -> 'Fresca'"""
    m = _ITEM_RE.match(text)
    text = m.group(2) if m else text
    text = re.sub(r"\(.*?\)", "", text)
    text = re.sub(r"^Pizza\s+", "", text, flags=re.IGNORECASE)
    return norm(text.replace("🌱", "").replace("VEGAN", ""))


def parse(html: str, place: Place, today: date) -> Menu:
    soup = BeautifulSoup(html, "html.parser")

    prices: dict[str, str] = {}
    for btn in soup.select(".ls-pricing .ls-btn"):
        m = _PRICE_RE.search(norm(btn.get_text()))
        if m:
            for num in re.findall(r"\d+", m.group(1)):
                prices[num] = f"{m.group(2)} Kč"

    day_card = None
    pizzas: list[str] = []
    for card in soup.select(".ls-card"):
        h3 = card.find("h3")
        if h3 is None:
            continue
        heading = norm(h3.get_text(" "))
        if "pizz" in heading.lower() and "výběr" in heading.lower():
            pizzas = [_short_pizza(norm(li.get_text(" "))) for li in card.find_all("li")]
            continue
        m = _DAY_RE.match(heading)
        if m and (int(m[1]), int(m[2])) == (today.day, today.month):
            day_card = card

    if day_card is None:
        return Menu(place, note="Na dnešek tu není polední menu.")

    chip = day_card.select_one("h3 .ls-chip")
    chip_text = norm(chip.get_text(" ")) if chip else ""

    items: list[tuple[str, str]] = []
    empty_slots = 0
    for li in day_card.find_all("li"):
        m = _ITEM_RE.match(norm(li.get_text(" ")))
        if not m:
            continue
        if not m.group(2):
            empty_slots += 1
            continue
        items.append((m.group(1), m.group(2)))

    # Svátek apod.: většina položek prázdná, v jedné je jen info text
    if empty_slots and len(items) <= 1:
        note = " – ".join(x for x in [chip_text, *(t for _, t in items)] if x)
        return Menu(place, note=note or "Dnes se polední menu nevaří.")

    dishes: list[Dish] = []
    if chip_text:
        dishes.append(Dish(name=chip_text, category=Category.SOUP))
    for num, text in items:
        if pizzas and "pizza" in text.lower() and "výběr" in text.lower():
            text = f"{text} – {', '.join(p for p in pizzas if p)}"
        dishes.append(Dish(name=text, price=prices.get(num), label=num))

    return Menu(place, dishes=dishes)
