"""Scraper pro restaurace z menicka.cz (https://www.menicka.cz/<id>.html)."""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup

from .models import NO_MENU, Category, Dish, Menu, Place, norm

URL = "https://www.menicka.cz/{id}.html"
_DATE_RE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")


def parse(html: str, place: Place, today: date) -> Menu:
    soup = BeautifulSoup(html, "html.parser")

    block = None
    for candidate in soup.select("div.menicka"):
        heading = candidate.find(class_="nadpis")
        m = _DATE_RE.search(heading.get_text() if heading else "")
        if m and date(int(m[3]), int(m[2]), int(m[1])) == today:
            block = candidate
            break
    if block is None:
        return Menu(place, note=NO_MENU)

    hours = None
    hours_el = block.select_one(".obedovycas em")
    if hours_el:
        hours = norm(hours_el.get_text()).replace("‐", "–")

    dishes: list[Dish] = []
    note = None
    for li in block.find_all("li"):
        item = li.find(class_="polozka")
        if item is None:
            # typicky "Pro tento den nebylo zadáno menu."
            text = norm(li.get_text(" "))
            if text:
                note = text
            continue
        label = None
        order = item.find(class_="poradi")
        if order is not None:
            label = norm(order.get_text()).rstrip(".") or None
            order.decompose()
        for allergen in item.find_all("em"):  # alergeny jako <em title="Lepek">1</em>
            allergen.decompose()
        name = norm(item.get_text(" "))
        if not name:
            continue
        price_el = li.find(class_="cena")
        dishes.append(
            Dish(
                name=name,
                price=norm(price_el.get_text()) if price_el else None,
                category=Category.SOUP if "polevka" in (li.get("class") or []) else Category.MAIN,
                label=label,
            )
        )

    return Menu(place, dishes=dishes, note=None if dishes else (note or NO_MENU), hours=hours)
