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
REFRESH_MINUTES = 60  # jak často se slevy a letáky obnovují na pozadí (Kupi.cz se mění nejvýš párkrát denně)
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
_UNIT_PRICE_RE = re.compile(r"([\d\s]+,\d+)\s*Kč\s*/\s*1\s*(kg|l)\b")


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


# Značky piv: jak je píše Kupi.cz (bez diakritiky, malými) -> jak se jim říká. Delší varianty první.
BEER_BRANDS: dict[str, str] = {
    "velkopopovicky kozel": "Kozel",
    "original budweiser budvar": "Budvar",
    "budweiser budvar": "Budvar",
    "pilsner urquell": "Plzeň",
    "svijansky maz svijany": "Svijany Máz",
    "svijany": "Svijany",
    "zlaty bazant": "Bažant",
    "corona extra": "Corona",
    "stella artois": "Stella",
    "grand pivovar zubr": "Zubr",
    "pivovar hubertus": "Hubertus",
    "novopacka liska": "Novopacké",
}
_SINGLE_WORD_BRANDS = (
    "radegast", "krusovice", "staropramen", "gambrinus", "branik", "bernard", "lobkowicz", "argus", "heineken",
    "guinness", "litovel", "excelent", "holba", "rychtar", "trumf", "klaster", "breznak", "zlatopramen", "proud",
    "starobrno", "ostravar", "zubr", "hubertus", "svijany", "rebel", "primator", "chotebor", "lev", "kelt",
    "kozel", "budvar", "pilsner", "birell", "tuborg", "carlsberg", "kvasnicak",
)
# Styl piva na začátku názvu -> krátce na konec
BEER_STYLES: dict[str, str] = {
    "svetly lezak": "ležák",
    "svetle vycepni": "výčepní",
    "svetle": "světlé",
    "cerny lezak": "černý ležák",
    "cerne vycepni": "černé výčepní",
    "polotmavy lezak": "polotmavý",
    "polotmave": "polotmavé",
    "silne tmave": "tmavé",
    "nefiltrovany svetly lezak": "nefiltrovaný ležák",
    "nefiltrovane svetle": "nefiltrované",
    "extra horky svetly lezak": "extra hořký ležák",
    "svatecni lezak": "sváteční ležák",
    "lezak": "ležák",
}


def beer_short_name(product: str) -> tuple[str | None, str]:
    """'Pivo světlý ležák 12° Velkopopovický Kozel' -> ('Kozel', '12° ležák').

    Vrací (značka, zbytek). Když značku nepozná, vrátí (None, název bez "Pivo").
    """
    words = re.sub(r"^pivo\s+", "", product.strip(), flags=re.IGNORECASE).split()
    simple = [_simplify(w) for w in words]

    def find(phrase: str) -> int | None:
        n = len(phrase.split())
        for i in range(len(simple) - n + 1):
            if " ".join(simple[i : i + n]) == phrase:
                return i
        return None

    brand = None
    for phrase, short in [*BEER_BRANDS.items(), *((b, None) for b in _SINGLE_WORD_BRANDS)]:
        i = find(phrase)
        if i is not None:
            n = len(phrase.split())
            brand = short or words[i]
            del words[i : i + n], simple[i : i + n]
            break
    style = ""
    for phrase, short in sorted(BEER_STYLES.items(), key=lambda kv: -len(kv[0])):
        if " ".join(simple[: len(phrase.split())]) == phrase:
            n = len(phrase.split())
            style = short
            del words[:n], simple[:n]
            break
    rest = " ".join(w for w in [" ".join(words), style] if w)
    if brand is None:
        name = " ".join(words) if not style else f"{style} {' '.join(words)}".strip()
        return None, (name[:1].upper() + name[1:]) if name else product
    return brand, rest


def unit_price(deal: kupi.Deal) -> tuple[float, str] | None:
    """Cena za 1 kg nebo 1 l z Kupi.cz ("31,97 Kč / 1 l" -> (31.97, "l")), jinak None."""
    m = _UNIT_PRICE_RE.search(deal.unit_price)
    return (float(m.group(1).replace(" ", "").replace(",", ".")), m.group(2)) if m else None


def beer_size(deal: kupi.Deal) -> tuple[int, float] | None:
    """Balení piva z akce: "6x 0.5 l" -> (6, 0.5), "0.33 l" -> (1, 0.33), jinak None."""
    amount = deal.amount.lower()
    pack = _PACK_COUNT_RE.search(amount)
    if pack:
        return int(pack.group(1)), float(pack.group(2).replace(",", "."))
    m = _VOLUME_RE.search(amount)
    return (1, float(m.group(1).replace(",", "."))) if m else None


def price_per_half_liter(deal: kupi.Deal) -> float | None:
    """Cena za 0,5 l (u piva jsme zvyklí počítat na půllitry, ne na litry)."""
    per_liter = price_per_liter(deal)
    return per_liter / 2 if per_liter else None


def price_per_liter(deal: kupi.Deal) -> float | None:
    up = unit_price(deal)
    return up[0] if up and up[1] == "l" else None


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
            "albert", "Albert supermarket", "🛒", 0x009FE3, "albert", ("Albert", "Albert supermarket"),
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
    """Stahuje a parsuje Kupi.cz na pozadí a drží hotové výsledky v paměti.

    Commandy dostanou poslední hotový výsledek okamžitě; nové se počítají jen při obnově na pozadí
    (`refresh_all`, každých REFRESH_MINUTES) nebo tlačítkem Obnovit (force). Parsování velkých stránek
    běží ve vlákně, aby nezastavilo bota.
    """

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher
        self._lock = asyncio.Lock()
        self._deals: dict[tuple[str, ...], DealsResult] = {}
        self._stores: dict[str, kupi.StorePage | None] | None = None

    async def _page(self, url: str, ttl: float, force: bool) -> tuple[str, float, bool]:
        """(html, čas stažení, bylo to čerstvé stažení?)"""
        started = time.time()
        html, fetched = await self.fetcher.get(url, ttl=ttl, force=force)
        return html, fetched, fetched >= started

    async def deals(self, categories: tuple[str, ...], force: bool = False) -> DealsResult:
        """Akce z daných kategorií Kupi.cz (všechny obchody, filtruje se až při zobrazení)."""
        if not force and categories in self._deals:
            return self._deals[categories]
        async with self._lock:
            if not force and categories in self._deals:  # mezitím to spočítal někdo jiný
                return self._deals[categories]
            result = await self._load_deals(categories, force)
            previous = self._deals.get(categories)
            if result.errors and previous is not None and not previous.errors:
                log.warning("Obnova %s selhala (%s), nechávám předchozí data", categories, result.errors)
                return previous
            self._deals[categories] = result
            return result

    async def _load_deals(self, categories: tuple[str, ...], force: bool) -> DealsResult:
        result = DealsResult()
        seen: set[str] = set()
        day = today()
        for category in categories:
            try:
                for page in range(1, MAX_PAGES + 1):
                    url = f"{kupi.BASE}/slevy/{category}" + (f"?page={page}" if page > 1 else "")
                    html, fetched, fresh = await self._page(url, DEALS_TTL, force)
                    result.fetched_at = min(result.fetched_at or fetched, fetched)
                    deals, has_next = await asyncio.to_thread(kupi.parse_deals, html, category, day, page)
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
        if not force and self._stores is not None:
            return self._stores
        pages: dict[str, kupi.StorePage | None] = {}
        day = today()
        for store in STORES.values():
            for branch in store.branches:
                try:
                    html, _, fresh = await self._page(f"{kupi.BASE}/obchod/{branch.kupi_path}", STORE_TTL, force)
                    pages[branch.kupi_path] = await asyncio.to_thread(kupi.parse_store, html, day)
                    if fresh:
                        await asyncio.sleep(PAGE_DELAY)
                except Exception:
                    log.exception("Načtení pobočky %s selhalo", branch.kupi_path)
                    # radši starší data pobočky než žádná
                    pages[branch.kupi_path] = (self._stores or {}).get(branch.kupi_path)
        self._stores = pages
        return pages

    async def refresh_all(self) -> None:
        """Obnova na pozadí: stáhne a naparsuje všechno znovu, commandy pak odpovídají hned."""
        await self.store_pages(force=True)
        await self.meat_deals(force=True)
        await self.drink_deals(force=True)
        await self.beer_deals(force=True)
