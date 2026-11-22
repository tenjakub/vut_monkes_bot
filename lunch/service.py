"""Spojuje stahování a parsování – tohle volají cogy."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import kam, lastrada, menicka, sesamo, ukarla
from .fetcher import Fetcher
from .models import Menu, Place

log = logging.getLogger(__name__)

TZ = ZoneInfo("Europe/Prague")
# Obnova na pozadí: stránky se stahují pravidelně samy, commandy pak berou data z cache.
# TTL je delší než interval, aby command nikdy nestahoval sám (jen mimo LUNCH_HOURS, kdy obnova neběží).
MENZA_REFRESH_MINUTES = 10  # KaM průběžně maže vyprodaná jídla, ať je to aktuální
RESTAURANT_REFRESH_MINUTES = 30
LUNCH_HOURS = (6, 20)  # obnova jen přes den (Purkyňova má výdej do 20:00)
MENZA_TTL = 15 * 60
RESTAURANT_TTL = 45 * 60


def is_lunch_time(now: datetime | None = None) -> bool:
    hour = (now or datetime.now(TZ)).hour
    return LUNCH_HOURS[0] <= hour < LUNCH_HOURS[1]


def today() -> date:
    return datetime.now(TZ).date()


def effective_ttl(ttl: float, now: datetime | None = None) -> float:
    """Mimo LUNCH_HOURS se jídelníčky nemění a obnova na pozadí neběží: co se dnes stáhlo, platí do půlnoci.
    Večer tak commandy nestahují znovu všechny stránky (dřív to i /co-jist zdržovalo na několik sekund)."""
    now = now or datetime.now(TZ)
    if is_lunch_time(now):
        return ttl
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return max(ttl, (now - midnight).total_seconds())


@dataclass(frozen=True)
class Restaurant:
    place: Place
    fetch_url: str
    parser: Callable[[str, Place, date], Menu]
    # volitelně doplňková stránka (velké menu s přísadami): stáhne se jednou za EXTRA_TTL a `extra(menu, html)`
    # menu doplní. Když se nepovede, menu se ukáže bez doplňků.
    extra_url: str | None = None
    extra: Callable[[Menu, str], Menu] | None = None


EXTRA_TTL = 12 * 60 * 60


RESTAURANTS: list[Restaurant] = [
    Restaurant(
        Place("u3opic", "U 3 opic", "https://www.menicka.cz/3225.html", "🐒", 0x8D6E63),
        menicka.URL.format(id=3225),
        menicka.parse,
    ),
    Restaurant(
        Place("padagali", "Padagali", "https://www.menicka.cz/4116.html", "🍛", 0xF59F00),
        menicka.URL.format(id=4116),
        menicka.parse,
    ),
    Restaurant(
        Place("lastrada", "La Strada", lastrada.URL, "🍝", 0x2F9E44),
        lastrada.URL,
        lastrada.parse,
    ),
    Restaurant(
        Place("ukarla", "U Karla", ukarla.URL, "🍺", 0xC92A2A),
        ukarla.URL,  # vlastní web, na menicka.cz (6695) chybí víkendy
        ukarla.parse,
    ),
    Restaurant(
        Place("portoriko", "Portoriko", "https://www.menicka.cz/8467.html", "🌴", 0x0CA678),
        menicka.URL.format(id=8467),
        menicka.parse,
    ),
    Restaurant(
        Place("sesamo", "Sesamo", sesamo.PAGE_URL, "🥐", 0xE8590C),
        sesamo.URL,  # vlastní web (Purkyňova), menu i o víkendu
        sesamo.parse,
        sesamo.BIG_MENU_URL,  # přísady pizz z velkého menu
        sesamo.add_descriptions,
    ),
]


# Naparsované menu podle URL: (čas stažení stránky, den, menu). Dokud se stránka znovu nestáhne,
# další command jen vezme hotový výsledek (parsování HTML je to nejpomalejší).
_parsed: dict[str, tuple[float, date, Menu]] = {}


async def _load(fetcher: Fetcher, place: Place, url: str, ttl: float, force: bool, parse) -> Menu:
    try:
        html, fetched = await fetcher.get(url, ttl=effective_ttl(ttl), force=force)
        day = today()
        cached = _parsed.get(url)
        if cached and cached[0] == fetched and cached[1] == day:
            menu = cached[2]
        else:
            menu = await asyncio.to_thread(parse, html)  # ve vlákně, ať se bot mezitím nezasekne
            menu.fetched_at = datetime.fromtimestamp(fetched, TZ)
            _parsed[url] = (fetched, day, menu)
        # kopie, protože volající do menu ještě dopisuje (otevírací doba)
        return replace(menu, dishes=list(menu.dishes))
    except Exception as exc:  # jeden rozbitý zdroj nesmí shodit celý výpis
        log.exception("Načtení %s selhalo", place.name)
        return Menu(place, error=f"Nepodařilo se načíst ({type(exc).__name__}).")


HOURS_TTL = 60 * 60
_overview: tuple[tuple[float, int], list[kam.Provoz]] | None = None  # ((čas stažení, hash), přehled)


async def kam_overview(fetcher: Fetcher, force: bool = False) -> list[kam.Provoz]:
    """Přehled otevíracích dob všech provozů KaM (menzy, pizzerie, kavárny…). Parsuje se jen po novém stažení."""
    global _overview
    html, fetched = await fetcher.get(kam.OVERVIEW_URL, ttl=effective_ttl(HOURS_TTL), force=force)
    key = (fetched, hash(html))
    if _overview is None or _overview[0] != key:
        _overview = (key, await asyncio.to_thread(kam.parse_overview, html))
    return _overview[1]


async def _menza_hours(fetcher: Fetcher, force: bool) -> dict[int, str]:
    """Otevírací doby menz pro dnešek; když se nepovede, prostě se nezobrazí."""
    try:
        day = today()
        return {p.provoz: p.hours_text(day) for p in await kam_overview(fetcher, force)}
    except Exception:
        log.exception("Načtení otevíracích dob menz selhalo")
        return {}


async def menza_menus(fetcher: Fetcher, group: str, force: bool = False) -> list[Menu]:
    menzy = [kam.MENZY[k] for k in kam.GROUPS[group].menzy]
    hours, *menus = await asyncio.gather(
        _menza_hours(fetcher, force),
        *(
            _load(fetcher, m, m.url, MENZA_TTL, force, lambda html, m=m: kam.parse(html, m))
            for m in menzy
        ),
    )
    for menza, menu in zip(menzy, menus):
        if menza.provoz in hours:
            menu.hours = hours[menza.provoz]
            menu.hours_label = "🕐 Dnes"
    return list(menus)


async def _with_extra(fetcher: Fetcher, r: Restaurant, menu: Menu) -> Menu:
    if not (r.extra and r.extra_url and menu.dishes):
        return menu
    try:
        html, _ = await fetcher.get(r.extra_url, ttl=EXTRA_TTL)
        return r.extra(menu, html)
    except Exception:  # doplňky nejsou nutné, menu se ukáže i bez nich
        log.exception("Doplnění menu %s selhalo", r.place.name)
        return menu


async def restaurant_menus(fetcher: Fetcher, force: bool = False) -> list[Menu]:
    day = today()
    menus = await asyncio.gather(
        *(
            _load(
                fetcher,
                r.place,
                r.fetch_url,
                RESTAURANT_TTL,
                force,
                lambda html, r=r: r.parser(html, r.place, day),
            )
            for r in RESTAURANTS
        )
    )
    return list(await asyncio.gather(*(_with_extra(fetcher, r, m) for r, m in zip(RESTAURANTS, menus))))
