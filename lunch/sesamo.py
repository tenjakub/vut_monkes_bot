"""Scraper denního menu SESAMO Bakery Pizza (Purkyňova 97c, https://sesamobrno.cz/#menu).

Menu je na webu v iframu ze souboru `menu_cz.html`: týden jako `.section` s nadpisem dne nebo rozsahu dnů
(„Pondělí 16.11.2026“, „Sobota 21.11.2026 – Neděle 22.11.2026“) a položkami `.item` (`.num`, `.text`, `.price`).
Položky bez čísla jsou polévky. Sekce `.aperitivo` (večerní akce) se přeskakuje.
"""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup

from .models import NO_MENU, Category, Dish, Menu, Place, norm

PAGE_URL = "https://sesamobrno.cz/#menu"  # pro lidi
URL = "https://sesamobrno.cz/menu_cz.html"  # samotné menu

_DATE_RE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})")


def _days(heading: str) -> tuple[date, date] | None:
    """'Sobota 21.11.2026 – Neděle 22.11.2026' -> (21. 11., 22. 11.); jeden den -> (den, den)."""
    found = [date(int(y), int(m), int(d)) for d, m, y in _DATE_RE.findall(heading)]
    return (found[0], found[-1]) if found else None


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
                dishes.append(Dish(name=name, price=price, label=label))
        if dishes:
            return Menu(place, dishes=dishes)
    return Menu(place, note=NO_MENU)
