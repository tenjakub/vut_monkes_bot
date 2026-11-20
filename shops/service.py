"""Slevy a letáky vybraných supermarketů z Kupi.cz – konfigurace obchodů, stahování a cache.

Ke Kupi.cz se chováme slušně: stránky se stahují postupně s pauzou, výsledky se cachují na několik
hodin a obnovují se na pozadí (uživatelské commandy pak jen čtou z cache).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

from lunch.fetcher import Fetcher
from lunch.service import today

from . import kupi

log = logging.getLogger(__name__)

DEALS_TTL = 4 * 3600
STORE_TTL = 6 * 3600
PAGE_DELAY = 1.0  # s mezi stránkami, ať Kupi.cz nezatěžujeme
MAX_PAGES = 6  # pojistka na kategorii

# Čerstvé maso po podkategoriích Kupi.cz (šunky, salámy, párky a ryby schválně ne – je jich stovky).
MEAT_CATEGORIES: dict[str, tuple[str, str]] = {
    "veprove-maso": ("🐖", "Vepřové"),
    "hovezi-maso": ("🐄", "Hovězí"),
    "drubez": ("🍗", "Drůbež"),
    "ostatni-maso": ("🍖", "Ostatní maso"),
}


@dataclass(frozen=True)
class Branch:
    label: str  # krátký popis pobočky do výpisu
    kupi_path: str  # /obchod/<kupi_path> na Kupi.cz


@dataclass(frozen=True)
class Store:
    key: str
    name: str
    emoji: str
    color: int
    kupi_chain: str  # slug řetězce na Kupi.cz (odkazy na všechny akce)
    shop_labels: tuple[str, ...]  # názvy obchodu v akcích na Kupi.cz, které platí pro tyhle pobočky
    branches: tuple[Branch, ...]


# Pobočky dohledané na Kupi.cz. Akce řetězců jsou většinou celostátní; letáky a otevírací doba
# jsou z konkrétní pobočky (např. BILLA Srbská má "malý leták", Albert Kosmova je supermarket).
STORES: dict[str, Store] = {
    s.key: s
    for s in [
        Store(
            "lidl", "Lidl", "🛒", 0x0050AA, "lidl", ("Lidl",),
            (
                Branch("Palackého", "lidl/lidl-brno-kralovo-pole"),
                Branch("Šumavská", "lidl/lidl-brno-veveri-sumavska"),
                Branch("Bayerova", "lidl/lidl-brno-veveri"),
            ),
        ),
        Store(
            "billa", "BILLA Srbská", "🛒", 0xED1C24, "billa", ("BILLA",),
            (Branch("Srbská", "billa/billa-brno-srbska"),),
        ),
        Store(
            # Albert na Semilasse = "Albert Brno, Kosmova" (supermarket) -> bez hypermarketových akcí
            "albert", "Albert Semilasso", "🛒", 0x009FE3, "albert", ("Albert", "Albert supermarket"),
            (Branch("Kosmova", "albert/albert-brno-kosmova"),),
        ),
        Store(
            "globus", "Globus Ivanovice", "🛒", 0x00843D, "globus", ("Globus",),
            (Branch("Ivanovice", "globus/globus-brno-ivanovice"),),
        ),
    ]
}


@dataclass
class DealsResult:
    deals: list[kupi.Deal] = field(default_factory=list)
    fetched_at: float | None = None
    errors: list[str] = field(default_factory=list)


class Shops:
    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher
        self._lock = asyncio.Lock()

    async def _page(self, url: str, ttl: float, force: bool) -> tuple[str, float, bool]:
        """(html, čas stažení, bylo to čerstvé stažení?)"""
        started = time.time()
        html, fetched = await self.fetcher.get(url, ttl=ttl, force=force)
        return html, fetched, fetched >= started

    async def meat_deals(self, force: bool = False) -> DealsResult:
        """Akce na čerstvé maso ze všech kategorií (všechny obchody, filtruje se až při zobrazení)."""
        async with self._lock:
            result = DealsResult()
            seen: set[str] = set()
            day = today()
            for category in MEAT_CATEGORIES:
                try:
                    for page in range(1, MAX_PAGES + 1):
                        url = f"{kupi.BASE}/slevy/{category}" + (f"?page={page}" if page > 1 else "")
                        html, fetched, fresh = await self._page(url, DEALS_TTL, force)
                        result.fetched_at = min(result.fetched_at or fetched, fetched)
                        deals, has_next = kupi.parse_deals(html, category, day, page)
                        for d in deals:
                            if d.id not in seen:
                                seen.add(d.id)
                                result.deals.append(d)
                        if not has_next:
                            break
                        if fresh:
                            await asyncio.sleep(PAGE_DELAY)
                except Exception as exc:
                    log.exception("Načtení slev z kategorie %s selhalo", category)
                    result.errors.append(f"{category}: {type(exc).__name__}")
            return result

    async def store_pages(self, force: bool = False) -> dict[str, kupi.StorePage | None]:
        """Stránky poboček (letáky + otevírací doba). Klíč = Branch.kupi_path."""
        pages: dict[str, kupi.StorePage | None] = {}
        day = today()
        for store in STORES.values():
            for branch in store.branches:
                try:
                    html, _, fresh = await self._page(f"{kupi.BASE}/obchod/{branch.kupi_path}", STORE_TTL, force)
                    pages[branch.kupi_path] = kupi.parse_store(html, day)
                    if fresh:
                        await asyncio.sleep(PAGE_DELAY)
                except Exception:
                    log.exception("Načtení pobočky %s selhalo", branch.kupi_path)
                    pages[branch.kupi_path] = None
        return pages

    async def warm_up(self) -> None:
        """Obnoví cache na pozadí (volá se pravidelně), aby commandy odpovídaly hned."""
        await self.meat_deals(force=True)
        await self.store_pages(force=True)
