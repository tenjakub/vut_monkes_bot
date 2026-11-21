"""Scraper poledního menu U Karla z jejich webu (https://ukarlabrno.cz/menu/pages/poledni-menu).

Na menicka.cz dávají jen všední dny, na vlastním webu je menu i na víkend. Stránka je jeden textový blok
(`div` s třídou `WysiwygContent_root…`): nadpis dne jako `<strong>Sobota 21.11. Polévka: Kuřecí vývar…</strong>`,
pod ním odstavce `1) Smažený kuřecí řízek, … 194` (cena na konci, bez „Kč“).
"""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup

from .models import Category, Dish, Menu, Place, norm

URL = "https://ukarlabrno.cz/menu/pages/poledni-menu"

_DAY_RE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.")
_SOUP_RE = re.compile(r"Polévka\s*:\s*(.+)$", re.IGNORECASE)
_ITEM_RE = re.compile(r"^(\d+)\)\s*(.+?)\s*(?:(\d+)\s*(?:Kč|,-)?)?$")


def parse(html: str, place: Place, today: date) -> Menu:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("div[class*='WysiwygContent_root']") or soup

    dishes: list[Dish] = []
    current = None  # den, pod jehož nadpisem právě jsme
    for p in content.find_all("p"):
        text = norm(p.get_text(" "))
        heading = p.find("strong")
        m = _DAY_RE.search(text) if heading else None
        if m:  # nadpis dne "Sobota 21.11. Polévka: …"
            current = (int(m[1]), int(m[2]))
            if current == (today.day, today.month):
                soup_m = _SOUP_RE.search(text)
                if soup_m:
                    dishes.append(Dish(name=norm(soup_m[1]), category=Category.SOUP))
            continue
        if current != (today.day, today.month):
            continue
        item = _ITEM_RE.match(text)
        if item:
            dishes.append(Dish(name=item[2], price=f"{item[3]} Kč" if item[3] else None, label=item[1]))

    if not dishes:
        return Menu(place, note="Na dnešek tu není zadané menu.")
    return Menu(place, dishes=dishes)
