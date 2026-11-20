"""Slevy a letáky vybraných supermarketů z Kupi.cz – konfigurace obchodů, stahování a cache.

Ke Kupi.cz se chováme slušně: stránky se stahují postupně s pauzou, výsledky se cachují na několik
hodin a obnovují se na pozadí (uživatelské commandy pak jen čtou z cache).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
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

# Nápoje: z těchhle kategorií se berou jen nápoje bez cukru (viz sugar_free()).
DRINK_CATEGORIES: dict[str, tuple[str, str]] = {
    "energeticke-a-iontove-napoje": ("⚡", "Energetické"),
    "limonady": ("🥤", "Limonády"),
}

# Kupi.cz často varianty neuvádí ("různé druhy"). Bez cukru je jisté jen tehdy, když to říká název
# nebo poznámka; u "různých druhů" značek, které verzi bez cukru vyrábějí, to je "možná".
_SUGAR_FREE_RE = re.compile(
    r"\bzero\b|bez cukru|sugar ?free|zero sugar|no sugar|\bnulka\b|\bmax\b|\blight\b|\bdiet\b|\bultra\b|0 ?% cukru"
)
_MIXED_RE = re.compile(r"(ruzne|vybrane|vsechny) druhy|\d+ druhy|ruzne prichute|vice druhu")
ZERO_BRANDS = (
    "red bull", "monster", "big shock", "semtex", "tiger", "rockstar", "burn", "hell", "powerade",
    "coca cola", "coca-cola", "pepsi", "kofola", "sprite", "fanta", "schweppes", "dr. pepper", "7up",
    "mirinda", "royal crown", "rc cola", "kinley", "mountain dew",
)

SUGAR_FREE = "yes"
MAYBE_SUGAR_FREE = "maybe"


def _simplify(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def sugar_free(deal: kupi.Deal) -> str | None:
    """SUGAR_FREE (jistě bez cukru), MAYBE_SUGAR_FREE (různé druhy značky, která má i bez cukru), jinak None."""
    name, note = _simplify(deal.product), _simplify(deal.note)
    if _SUGAR_FREE_RE.search(name) or _SUGAR_FREE_RE.search(note):
        return SUGAR_FREE
    if _MIXED_RE.search(note) and any(brand in name for brand in ZERO_BRANDS):
        return MAYBE_SUGAR_FREE
    return None


# --- pivo -----------------------------------------------------------------------------------

BEER_CATEGORIES: dict[str, tuple[str, str]] = {"pivo": ("🍺", "Pivo")}

BEER_BOTTLE = "lahev"
BEER_CAN = "plechovka"
BEER_PACK = "multipack"
BEER_PACKS: dict[str, tuple[str, str]] = {
    BEER_BOTTLE: ("🍾", "Lahve"),
    BEER_CAN: ("🥫", "Plechovky"),
    BEER_PACK: ("📦", "Basy a multipacky"),
}
# PET lahve, sudy a dárková balení (s krýglem, sklenicí, "metr piv"…) nechceme
_BEER_EXCLUDE_RE = re.compile(
    r"\bpet\b|\bsud|soudek|darkov|krygl|sklenic|gobletk|dzban|\bsal[au]\b|\bmetr\b|adventni|ikonicke sklo|korbel"
)
_PACK_COUNT_RE = re.compile(r"(\d+)\s*x\s*(\d+(?:[.,]\d+)?)\s*l")
_VOLUME_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*l\b")
_UNIT_PRICE_RE = re.compile(r"([\d\s]+,\d+)\s*Kč\s*/\s*1\s*l")


def beer_pack(deal: kupi.Deal) -> str | None:
    """Typ balení piva (BEER_BOTTLE / BEER_CAN / BEER_PACK), nebo None pro PET, sudy a dárková balení."""
    text = _simplify(f"{deal.product} {deal.note}")
    if _BEER_EXCLUDE_RE.search(text):
        return None
    amount = deal.amount.lower()
    pack = _PACK_COUNT_RE.search(amount)
    volume = float((pack.group(2) if pack else (_VOLUME_RE.search(amount) or [None, "0"])[1]).replace(",", "."))
    if volume > 1.0:  # 1,5 l a víc = PET nebo soudek
        return None
    per_liter = price_per_liter(deal)
    if per_liter and per_liter > 150:  # sběratelské/dárkové lahve (1 l Pilsner za 229 Kč), ne akce na pivo
        return None
    if (pack and int(pack.group(1)) > 1) or "basa" in text or "prepravk" in text or "zaloha na lahve" in text:
        return BEER_PACK
    if "plech" in text:
        return BEER_CAN
    return BEER_BOTTLE


def price_per_liter(deal: kupi.Deal) -> float | None:
    m = _UNIT_PRICE_RE.search(deal.unit_price)
    return float(m.group(1).replace(" ", "").replace(",", ".")) if m else None


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


# Pobočky dohledané na Kupi.cz. Akce (maso, nápoje, pivo) jsou na Kupi.cz za celý řetězec, proto
# se obchody jmenují obecně ("BILLA"). Letáky a otevírací doba jsou z konkrétní pobočky a ta se
# u letáků ukazuje (BILLA Srbská má "malý leták", Albert na Semilasse je supermarket -> bez
# hypermarketových akcí).
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
            "billa", "BILLA", "🛒", 0xED1C24, "billa", ("BILLA",),
            (Branch("Srbská", "billa/billa-brno-srbska"),),
        ),
        Store(
            # Albert na Semilasse = "Albert Brno, Kosmova" (supermarket) -> bez hypermarketových akcí
            "albert", "Albert", "🛒", 0x009FE3, "albert", ("Albert", "Albert supermarket"),
            (Branch("Semilasso (Kosmova)", "albert/albert-brno-kosmova"),),
        ),
        Store(
            "globus", "Globus", "🛒", 0x00843D, "globus", ("Globus",),
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

    async def deals(self, categories: tuple[str, ...], force: bool = False) -> DealsResult:
        """Akce z daných kategorií Kupi.cz (všechny obchody, filtruje se až při zobrazení)."""
        async with self._lock:
            result = DealsResult()
            seen: set[str] = set()
            day = today()
            for category in categories:
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

    async def meat_deals(self, force: bool = False) -> DealsResult:
        return await self.deals(tuple(MEAT_CATEGORIES), force)

    async def drink_deals(self, force: bool = False) -> DealsResult:
        return await self.deals(tuple(DRINK_CATEGORIES), force)

    async def beer_deals(self, force: bool = False) -> DealsResult:
        return await self.deals(tuple(BEER_CATEGORIES), force)

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
        await self.drink_deals(force=True)
        await self.beer_deals(force=True)
        await self.store_pages(force=True)
