"""Hledání akcí pro hlídání (/hlidat): jaké akce odpovídají hledanému slovu a ceně. Bez discord.py a databáze."""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date

from . import kupi
from .service import STORES, _PACK_COUNT_RE, _simplify, beer_short_name

_WORD_RE = re.compile(r"\w+")
_PRICE_INPUT_RE = re.compile(r"^\s*(\d+(?:[.,]\d{1,2})?)\s*(?:kč|,-)?\s*$", re.IGNORECASE)
STORE_OF_LABEL = {label: store for store in STORES.values() for label in store.shop_labels}


def words(query: str) -> list[str]:
    return _WORD_RE.findall(_simplify(query))


def parse_price(text: str) -> float | None:
    """'25' / '25,90' / '25 Kč' -> číslo; prázdné -> None; nesmysl -> ValueError."""
    if not text.strip():
        return None
    m = _PRICE_INPUT_RE.match(text)
    if not m:
        raise ValueError(text)
    value = float(m.group(1).replace(",", "."))
    if value <= 0:
        raise ValueError(text)
    return value


def piece_price(deal: kupi.Deal) -> float | None:
    """Cena za kus: u multipacků („6x 0.5 l“) cena dělená počtem, jinak cena akce."""
    m = re.search(r"(\d[\d\s ]*)(?:,(\d+))?", deal.price)
    if not m:
        return None
    price = float(re.sub(r"\D", "", m.group(1)) + "." + (m.group(2) or "0"))
    pack = _PACK_COUNT_RE.search(deal.amount.lower())
    count = int(pack.group(1)) if pack else 1
    return price / count if count > 1 else price


def _similar(wanted: str, word: str) -> bool:
    """Slovo z dotazu odpovídá slovu z názvu: stejné, nebo stejný začátek (čeština skloňuje: „prsa“ ~ „prsní“,
    „plzen“ ~ „plzenske“). Shodný začátek musí mít aspoň 3 znaky a nejvýš jeden znak dotazu navíc."""
    if wanted == word:
        return True
    common = 0
    for a, b in zip(wanted, word):
        if a != b:
            break
        common += 1
    return common >= max(3, len(wanted) - 1)


def hit_key(deal: kupi.Deal) -> str:
    """Stálý klíč akce pro „už o ní ví“: obchod, produkt, balení, cena a konec platnosti. Kupi.cz má stejnou
    akci někdy pod dvěma ID (Albert / Albert supermarket), nová akce za týden je ale nová zpráva."""
    store = STORE_OF_LABEL.get(deal.shop)
    valid_to = deal.valid_to.isoformat() if deal.valid_to else ""
    return "|".join((store.key if store else deal.shop, deal.product.lower(), deal.amount, deal.price, valid_to))


def matches(query: str, max_price: float | None, deals: Iterable[kupi.Deal], day: date) -> list[kupi.Deal]:
    """Akce v našich obchodech, které platí dnes nebo začnou později, obsahují všechna slova z dotazu
    (bez ohledu na diakritiku, velikost písmen a koncovky) a vejdou se do ceny. Seřazené od nejlevnější."""
    wanted = words(query)
    if not wanted:
        return []
    found = []
    seen = set()
    for d in deals:
        if d.shop not in STORE_OF_LABEL or (d.valid_to and d.valid_to < day):
            continue
        brand = beer_short_name(d.product)[0] if d.category == "pivo" else None  # „Plzeň“ najde Pilsner Urquell
        name = set(words(f"{d.product} {d.note} {brand or ''}"))
        if not all(any(_similar(w, n) for n in name) for w in wanted):
            continue
        price = piece_price(d)
        if max_price is not None and (price is None or price > max_price):
            continue
        key = hit_key(d)
        if key in seen:  # stejná akce jako „Albert“ i „Albert supermarket“ jen jednou
            continue
        seen.add(key)
        found.append(d)
    return sorted(found, key=lambda d: (piece_price(d) or 0, d.product))
