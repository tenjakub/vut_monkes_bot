"""Spojuje stahování a parsování – tohle volají cogy."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from . import kam, lastrada, menicka
from .fetcher import Fetcher
from .models import Menu, Place

log = logging.getLogger(__name__)

TZ = ZoneInfo("Europe/Prague")
MENZA_TTL = 5 * 60  # KaM průběžně maže vyprodaná jídla, takže kratší cache
RESTAURANT_TTL = 30 * 60


def today() -> date:
    return datetime.now(TZ).date()


@dataclass(frozen=True)
class Restaurant:
    place: Place
    fetch_url: str
    parser: Callable[[str, Place, date], Menu]


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
        Place("ukarla", "U Karla", "https://www.menicka.cz/6695.html", "🍺", 0xC92A2A),
        menicka.URL.format(id=6695),
        menicka.parse,
    ),
    Restaurant(
        Place("portoriko", "Portoriko", "https://www.menicka.cz/8467.html", "🌴", 0x0CA678),
        menicka.URL.format(id=8467),
        menicka.parse,
    ),
]


async def _load(fetcher: Fetcher, place: Place, url: str, ttl: float, force: bool, parse) -> Menu:
    try:
        html, fetched = await fetcher.get(url, ttl=ttl, force=force)
        menu = parse(html)
        menu.fetched_at = datetime.fromtimestamp(fetched, TZ)
        return menu
    except Exception as exc:  # jeden rozbitý zdroj nesmí shodit celý výpis
        log.exception("Načtení %s selhalo", place.name)
        return Menu(place, error=f"Nepodařilo se načíst ({type(exc).__name__}).")


HOURS_TTL = 60 * 60


async def _menza_hours(fetcher: Fetcher, force: bool) -> dict[int, str]:
    """Otevírací doby menz pro dnešek; když se nepovede, prostě se nezobrazí."""
    try:
        html, _ = await fetcher.get(kam.OVERVIEW_URL, ttl=HOURS_TTL, force=force)
        return kam.parse_hours(html, today())
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


async def restaurant_menus(fetcher: Fetcher, force: bool = False) -> list[Menu]:
    day = today()
    return list(
        await asyncio.gather(
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
    )
