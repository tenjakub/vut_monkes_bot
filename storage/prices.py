"""Historie cen akcí z Kupi.cz: podklad pro 🔥/🎣 u slev a pro budoucí statistiky (vývoj cen).

Jeden řádek = jedna akce (ID akce z Kupi.cz), ne jeden den: akce trvá obvykle týden, takže je to ~100 nových
řádků denně (všechny obchody na Kupi.cz ve stahovaných kategoriích), za rok jednotky MB.

Porovnává se stejný produkt (slug z Kupi.cz) ve stejném balení, podle ceny za kg/l (když ji Kupi uvádí), jinak
podle ceny za balení. Bereme jen akční ceny (běžné ceny Kupi.cz nemá), takže:
- 🔥 HOT = nejnižší cena, za jakou jsme produkt v akci zatím viděli (aspoň MIN_HISTORY jiných akcí), a zároveň
  znatelně pod obvyklou akční cenou (když je produkt v akci pořád za stejnou cenu, nic zvláštního to není),
- 🎣 BAIT = akce tvrdí slevu v %, ale cena je vyšší, než za kolik produkt v akci obvykle bývá (medián).
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

from shops import kupi
from shops.service import unit_price
from utils.text import price_value

from .db import Database

HOT = "hot"
BAIT = "bait"
MARKS = {HOT: "🔥", BAIT: "🎣"}
MIN_HISTORY = 3  # kolik jiných akcí produktu musíme znát, než něco tvrdíme
HISTORY_DAYS = 365  # starší akce se do porovnání nepočítají (ceny rostou)
HOT_BELOW = 0.97  # 🔥 jen když je cena aspoň o 3 % pod obvyklou akční cenou
BAIT_ABOVE = 1.02  # 🎣 až když je cena znatelně nad obvyklou akční cenou (ne kvůli haléřům)
BATCH = 400  # produktů v jednom dotazu (limit počtu parametrů SQLite)

_SLUG_RE = re.compile(r"/sleva/([^/?#]+)")


def product_key(deal: kupi.Deal) -> str:
    m = _SLUG_RE.search(deal.url)
    return m.group(1) if m else deal.product.lower()


@dataclass(frozen=True)
class PricePoint:
    deal_id: str
    shop: str
    price: float
    unit_price: float | None
    unit: str | None
    percent: int | None
    first_seen: date


def _row(deal: kupi.Deal, day: date) -> tuple | None:
    price = price_value(deal.price)
    if price is None:
        return None
    up = unit_price(deal)
    return (
        deal.id, product_key(deal), deal.product, deal.amount, deal.shop, deal.category, price,
        up[0] if up else None, up[1] if up else None, deal.percent,
        deal.valid_from.isoformat() if deal.valid_from else None,
        deal.valid_to.isoformat() if deal.valid_to else None,
        day.isoformat(), day.isoformat(),
    )


_UPSERT = """
INSERT INTO deal_price (deal_id, product, name, amount, shop, category, price, unit_price, unit, percent,
                        valid_from, valid_to, first_seen, last_seen)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT (deal_id) DO UPDATE SET
    price = excluded.price, unit_price = excluded.unit_price, unit = excluded.unit, percent = excluded.percent,
    valid_from = excluded.valid_from, valid_to = excluded.valid_to, last_seen = excluded.last_seen
"""


async def record(db: Database, deals: Iterable[kupi.Deal], day: date) -> int:
    """Uloží akce (nové přidá, u známých posune `last_seen`). Vrací počet uložených akcí."""
    rows = {r[0]: r for d in deals if (r := _row(d, day))}
    if rows:
        async with db.transaction() as tx:
            await tx.executemany(_UPSERT, list(rows.values()))
    return len(rows)


async def history(db: Database, deals: Iterable[kupi.Deal], day: date) -> dict[tuple[str, str], list[PricePoint]]:
    """Známé akce produktů za posledních HISTORY_DAYS: {(produkt, balení): [ceny]}."""
    keys = sorted({(product_key(d), d.amount) for d in deals})
    since = (day - timedelta(days=HISTORY_DAYS)).isoformat()
    found: dict[tuple[str, str], list[PricePoint]] = {}
    products = sorted({k for k, _ in keys})
    wanted = set(keys)
    for i in range(0, len(products), BATCH):
        chunk = products[i:i + BATCH]
        marks = ",".join("?" * len(chunk))
        rows = await db.fetchall(
            "SELECT deal_id, product, amount, shop, price, unit_price, unit, percent, first_seen FROM deal_price "
            f"WHERE product IN ({marks}) AND last_seen >= ?",
            (*chunk, since),
        )
        for r in rows:
            key = (r["product"], r["amount"])
            if key in wanted:
                found.setdefault(key, []).append(PricePoint(
                    r["deal_id"], r["shop"], r["price"], r["unit_price"], r["unit"], r["percent"],
                    date.fromisoformat(r["first_seen"]),
                ))
    return found


def _comparable(deal: kupi.Deal, points: list[PricePoint]) -> tuple[float, list[float]] | None:
    """Cena akce a ceny ostatních akcí ve stejných jednotkách (za kg/l, jinak za balení)."""
    others = [p for p in points if p.deal_id != deal.id]
    up = unit_price(deal)
    if up and all(p.unit_price is not None and p.unit == up[1] for p in others):
        return up[0], [p.unit_price for p in others]  # type: ignore[misc]
    price = price_value(deal.price)
    return (price, [p.price for p in others]) if price is not None else None


def mark(deal: kupi.Deal, points: list[PricePoint]) -> str | None:
    """HOT, BAIT nebo None (málo dat / nic zvláštního)."""
    compared = _comparable(deal, points)
    if compared is None:
        return None
    price, others = compared
    if len(others) < MIN_HISTORY:
        return None
    typical = statistics.median(others)
    if price <= min(others) and price < typical * HOT_BELOW:
        return HOT
    if deal.percent and price > typical * BAIT_ABOVE:
        return BAIT
    return None


async def marks(db: Database, deals: list[kupi.Deal], day: date) -> dict[str, str]:
    """{ID akce: HOT/BAIT} pro akce, u kterých je co říct."""
    known = await history(db, deals, day)
    result = {}
    for d in deals:
        m = mark(d, known.get((product_key(d), d.amount), []))
        if m:
            result[d.id] = m
    return result
