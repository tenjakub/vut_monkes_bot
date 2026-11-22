"""Scraper jídelníčků menz VUT z webu KaM (https://www.kam.vut.cz/?p=menu&provoz=N)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from bs4 import BeautifulSoup

from utils.holidays import cz_holidays

from .models import Category, Dish, Menu, Place, norm

MENU_URL = "https://www.kam.vut.cz/?p=menu&provoz={provoz}"
OVERVIEW_URL = "https://www.kam.vut.cz/?p=otdo"

# Výchozí cenová kategorie na webu KaM:
#   slcen1 = student VUT, slcen2 = zaměstnanec VUT, slcen3 = externí, slcen4 = student jiné VŠ
PRICE_CLASS = "slcen1"
PRICE_LABEL = "student VUT"

_ECONOMY_RE = re.compile(r"^\s*Economy\s*(\d*)\s*:\s*", re.IGNORECASE)
_PRICE_RE = re.compile(r"(\d+)")


@dataclass(frozen=True)
class Menza(Place):
    provoz: int = 0


def _menza(key: str, name: str, provoz: int, emoji: str, color: int) -> Menza:
    return Menza(
        key=key,
        name=name,
        url=MENU_URL.format(provoz=provoz),
        emoji=emoji,
        color=color,
        provoz=provoz,
    )


# ID provozů jsou vidět na https://www.kam.vut.cz/?p=otdo
MENZY: dict[str, Menza] = {
    m.key: m
    for m in [
        _menza("kolejni", "Menza Kolejní", 20, "🏢", 0x2B8A3E),
        _menza("mozzarella", "Pizzerie Mozzarella", 18, "🍕", 0xE03131),
        _menza("stary_pivovar", "Menza Starý pivovar", 5, "🍺", 0xF08C00),
        _menza("purkynova", "Menza Purkyňova", 10, "🏫", 0x1971C2),
        _menza("q_technicka", "Restaurace Q - Technická", 13, "⚙️", 0x6741D9),
        _menza("fch", "Menza FCH", 17, "🧪", 0x0C8599),
        _menza("rybkova", "Restaurace Rybkova", 26, "🐟", 0xC2255C),
    ]
}


@dataclass(frozen=True)
class MenzaGroup:
    key: str
    label: str  # text na tlačítku / v nabídce commandu
    menzy: tuple[str, ...]


GROUPS: dict[str, MenzaGroup] = {
    g.key: g
    for g in [
        MenzaGroup("ppv", "Kolejní + Mozzarella + Starý pivovar", ("kolejni", "mozzarella", "stary_pivovar")),
        MenzaGroup("purkyne", "Purkyňova + Starý pivovar", ("purkynova", "stary_pivovar")),
        MenzaGroup(
            "vse",
            "Všechny menzy s Economy",
            ("kolejni", "mozzarella", "stary_pivovar", "purkynova", "q_technicka", "fch", "rybkova"),
        ),
    ]
}


def _format_price(text: str) -> str | None:
    m = _PRICE_RE.search(text)
    return f"{m.group(1)} Kč" if m else None


def _category(type_code: str) -> Category:
    code = type_code.strip().upper()
    if code.startswith("P"):
        return Category.SOUP
    if code.startswith(("H", "M")):  # H = hlavní jídlo, Mx = menu X
        return Category.MAIN
    return Category.SIDE


def parse(html: str, menza: Menza) -> Menu:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id=f"m{menza.provoz}") or soup.find("table", class_="htab")
    if table is None:
        return Menu(menza, note="Dnes tu není žádný jídelníček (zavřeno?).")

    dishes: list[Dish] = []
    for tr in table.find_all("tr"):
        # česky název je ve sloupci s třídou jjjaz1jjj, anglický v jjjaz2jjj
        name_td = tr.find("td", class_="jjjaz1jjj") or tr.find("td", class_="levyjid")
        if name_td is None:
            continue
        for small in name_td.find_all("small"):  # alergeny
            small.decompose()
        name = norm(name_td.get_text(" "))
        if not name:
            continue
        name = re.sub(r"\s+,", ",", name)

        type_td = tr.find("td", class_="levy")
        price_td = tr.find("td", class_=PRICE_CLASS)
        dish = Dish(
            name=name,
            price=_format_price(price_td.get_text()) if price_td else None,
            category=_category(type_td.get_text() if type_td else ""),
        )

        m = _ECONOMY_RE.match(name)
        if m:
            dish.economy = True
            dish.name = name[m.end():].strip()
            dish.label = f"E{m.group(1)}" if m.group(1) else "E"
            dish.category = Category.MAIN
        dishes.append(dish)

    # Economy chceme vždy nahoře (sort je stabilní, pořadí z webu zůstane)
    dishes.sort(key=lambda d: 0 if d.economy else 1)
    return Menu(menza, dishes=dishes)


# ---------------------------------------------------------------------------
# Otevírací doby z přehledu https://www.kam.vut.cz/?p=otdo
#
# Tabulka table.ntab má sloupce: provoz | A (stav) | PO – ČT* | PÁ | SO + NE**
#   *  v pracovní den před státním svátkem platí doba jako v PÁ
#   ** platí i pro státní svátky
# Stav "A" je aktuální (mimo otevírací dobu tam bývá "z"), proto z něj bereme jen
# x = dočasně přerušen provoz a a = pro veřejnost zavřeno (akce).

_INTERVAL_RE = re.compile(r"(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})")
_PROVOZ_RE = re.compile(r"provoz=(\d+)")
_STATE_NOTES = {"x": "dočasně přerušen provoz", "a": "pro veřejnost zavřeno (akce)"}


def _hours_column(day: date) -> int:
    """Index sloupce s časy (0 = PO–ČT, 1 = PÁ, 2 = SO+NE) pro daný den."""
    holidays = cz_holidays(day.year) | cz_holidays(day.year + 1)
    if day.weekday() >= 5 or day in holidays:
        return 2
    if day.weekday() == 4 or (day + timedelta(days=1)) in holidays:
        return 1
    return 0


@dataclass(frozen=True)
class Provoz:
    """Jeden řádek přehledu otevíracích dob: menza, pizzerie, kavárna, bufet…"""

    provoz: int
    name: str  # "Menza Kolejní"
    address: str  # "Kolejní 2, Brno-Královo Pole"
    columns: tuple[tuple[tuple[str, str], ...], ...]  # intervaly (od, do) pro PO–ČT / PÁ / SO+NE
    closed_note: str | None = None  # aktuální stav x / a – platí jen pro dnešek

    def intervals(self, day: date) -> list[tuple[str, str]]:
        return list(self.columns[_hours_column(day)])

    def hours_text(self, day: date, today: bool = True) -> str:
        """"11:00–14:30" | "11:00–14:30, 17:00–20:00" | "zavřeno" | "zavřeno (důvod)"."""
        if today and self.closed_note:
            return f"zavřeno ({self.closed_note})"
        return ", ".join(f"{a}–{b}" for a, b in self.intervals(day)) or "zavřeno"


def parse_overview(html: str) -> list[Provoz]:
    """Všechny provozy z přehledu otevíracích dob, v pořadí jako na webu."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="ntab")
    if table is None:
        return []
    result: list[Provoz] = []
    for tr in table.find_all("tr"):
        link = tr.find("a", href=_PROVOZ_RE)
        cells = tr.find_all("td", recursive=False)
        if link is None or len(cells) < 5:
            continue
        name_el, address_el = link.find("b"), link.find("small")
        name = norm(name_el.get_text() if name_el else link.get_text(" ")).rstrip("*").strip()
        state = norm(cells[1].get_text()).lower()
        result.append(Provoz(
            provoz=int(_PROVOZ_RE.search(link["href"]).group(1)),
            name=name,
            address=norm(address_el.get_text()) if address_el else "",
            columns=tuple(tuple(_INTERVAL_RE.findall(c.get_text(" "))) for c in cells[2:5]),
            closed_note=_STATE_NOTES.get(state),
        ))
    return result


def parse_hours(html: str, day: date) -> dict[int, str]:
    """{provoz: "11:00–14:30" | "11:00–14:30, 17:00–20:00" | "zavřeno" | "zavřeno (důvod)"} pro daný den."""
    return {p.provoz: p.hours_text(day) for p in parse_overview(html)}
