"""Parser stránek Kupi.cz (akce a letáky supermarketů).

Používáme jen veřejné HTML stránky, které robots.txt povoluje:
- kategorie slev: https://www.kupi.cz/slevy/<kategorie>[?page=N]
- stránka pobočky: https://www.kupi.cz/obchod/<řetězec>/<pobočka> (letáky platné pro pobočku, otevírací doba)
Interní AJAX endpointy (/get-slevy, /get-letaky …) robots.txt zakazuje – nepoužívat.

Struktura kategorie: každý produkt (div.product--wrap) má pod sebou řádky slev (div.discount_row),
jeden řádek = jedna akce v jednom obchodě (název obchodu, cena, sleva v %, platnost, odkaz na leták).
Nahoře bývají sponzorované produkty jiných obchodů, proto se řádky vždy filtrují podle obchodu.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, timedelta

from bs4 import BeautifulSoup, Tag

from lunch.models import norm

BASE = "https://www.kupi.cz"

_DATE_RE = re.compile(r"(\d{1,2})\.\s*(\d{1,2})\.")
_PERCENT_RE = re.compile(r"(\d+)\s*%")
_LD_DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]


@dataclass(frozen=True)
class Deal:
    id: str
    product: str
    amount: str  # "1 kg", "100 g", "" když není
    shop: str  # název obchodu tak, jak ho uvádí Kupi ("Lidl", "Albert supermarket", …)
    price: str  # "99,90 Kč"
    percent: int | None  # sleva v %, pokud ji Kupi uvádí
    valid_from: date | None
    valid_to: date | None
    category: str  # slug kategorie Kupi ("drubez", …)
    url: str  # detail produktu na Kupi.cz

    def is_current(self, today: date) -> bool:
        return (self.valid_from is None or self.valid_from <= today) and (
            self.valid_to is None or self.valid_to >= today
        )


@dataclass(frozen=True)
class Leaflet:
    title: str
    url: str
    valid_from: date | None
    valid_to: date | None
    image: str | None = None


@dataclass(frozen=True)
class StorePage:
    name: str | None
    hours: dict[int, str]  # den v týdnu (0 = pondělí) -> "07:00–21:00"
    leaflets: list[Leaflet]


def _text(el: Tag | None) -> str:
    return norm(el.get_text(" ")) if el else ""


def _resolve(day: int, month: int, today: date) -> date:
    """Datum bez roku: vezme rok tak, aby datum bylo nejblíž dnešku (kvůli přelomu roku)."""
    candidates = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            candidates.append(date(year, month, day))
        except ValueError:
            continue
    return min(candidates, key=lambda d: abs((d - today).days))


def parse_validity(text: str, today: date) -> tuple[date | None, date | None]:
    """'platí do úterý 24. 11.' / 'čt 26. 11. – ne 29. 11.' / 'zítra končí' / 'dnes končí' -> (od, do)."""
    t = text.lower()
    if "zítra končí" in t:
        return None, today + timedelta(days=1)
    if "dnes končí" in t:
        return None, today
    dates = [_resolve(int(d), int(m), today) for d, m in _DATE_RE.findall(t)]
    if len(dates) >= 2:
        return dates[0], dates[-1]
    if len(dates) == 1:
        return (None, dates[0]) if " do " in f" {t} " or t.startswith("do") else (dates[0], None)
    return None, None


def parse_deals(html: str, category: str, today: date, page: int = 1) -> tuple[list[Deal], bool]:
    """Vrátí (akce, existuje stránka page+1)."""
    soup = BeautifulSoup(html, "html.parser")
    deals: list[Deal] = []
    for product in soup.select("div.product--wrap"):
        container = product.parent
        name = _text(product.select_one(".product_name strong")) or _text(product.select_one(".product_name a"))
        amount = _text(product.select_one(".product_name .nowrap"))
        link = product.select_one("a.product_link_history[href^='/sleva/']")
        url = BASE + link["href"] if link else BASE
        product_id = product.get("data-product")
        for row in container.select("div.discount_row"):
            if product_id and row.get("data-product") not in (None, product_id):
                continue  # řádek patří jinému produktu
            shop = _text(row.select_one(".discounts_shop_name"))
            price = _text(row.select_one(".discount_price_value"))
            if not shop or not price:
                continue
            pct = _PERCENT_RE.search(_text(row.select_one(".discount_percentage")))
            valid_from, valid_to = parse_validity(_text(row.select_one(".discounts_validity")), today)
            deals.append(
                Deal(
                    id=row.get("data-discount") or f"{name}|{shop}|{price}",
                    product=name,
                    amount=amount,
                    shop=shop,
                    price=price,
                    percent=int(pct.group(1)) if pct else None,
                    valid_from=valid_from,
                    valid_to=valid_to,
                    category=category,
                    url=url,
                )
            )
    has_next = soup.select_one(f"a[href='/slevy/{category}?page={page + 1}']") is not None
    return deals, has_next


def parse_store(html: str, today: date) -> StorePage:
    soup = BeautifulSoup(html, "html.parser")
    name = None
    hours: dict[int, str] = {}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or "")
        except ValueError:
            continue
        if not isinstance(data, dict) or "openingHours" not in data:
            continue
        name = data.get("name")
        for entry in data["openingHours"]:  # "Mo 07:00 - 21:00"
            m = re.match(r"(\w\w)\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", entry)
            if m and m.group(1) in _LD_DAYS:
                start, end = (re.sub(r"^0(?=\d)", "", t) for t in (m.group(2), m.group(3)))  # 07:00 -> 7:00
                hours[_LD_DAYS.index(m.group(1))] = f"{start}–{end}"

    leaflets: list[Leaflet] = []
    block = soup.select_one(".shop_leaflets_block") or soup
    seen = set()
    for item in block.select(".leaflet-item"):
        link = item.select_one("a.leaflet-item--link[href^='/letak/']")
        if link is None or link["href"] in seen:
            continue
        seen.add(link["href"])
        valid_from, valid_to = parse_validity(_text(item.select_one(".leaflet-item--validity")), today)
        img = item.select_one("img")
        leaflets.append(
            Leaflet(
                title=_text(item.select_one(".leaflet-item--name")) or _text(link),
                url=BASE + link["href"],
                valid_from=valid_from,
                valid_to=valid_to,
                image=img.get("src") if img else None,
            )
        )
    return StorePage(name=name, hours=hours, leaflets=leaflets)
