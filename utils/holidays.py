"""Státní svátky v ČR a svátky, kdy mají velké obchody ze zákona zavřeno. Bez discord.py."""

from __future__ import annotations

from datetime import date, timedelta

# (měsíc, den) státních svátků s pevným datem
_FIXED = [(1, 1), (5, 1), (5, 8), (7, 5), (7, 6), (9, 28), (10, 28), (11, 17), (12, 24), (12, 25), (12, 26)]

# Zákon č. 223/2016 Sb.: obchody nad 200 m² mají v tyhle dny zavřeno, 24. 12. jen do 12:00.
_SHOPS_CLOSED = [(1, 1), (5, 8), (9, 28), (10, 28), (12, 25), (12, 26)]
CHRISTMAS_EVE_CLOSE = "12:00"


def easter(year: int) -> date:
    """Velikonoční neděle (anonymní gregoriánský algoritmus)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 19 * l) // 433
    month = (h + l - 7 * m + 90) // 25
    day = (h + l - 7 * m + 33 * month + 19) % 32
    return date(year, month, day)


def cz_holidays(year: int) -> set[date]:
    """Státní svátky a ostatní svátky (dny pracovního klidu), včetně Velkého pátku a Velikonočního pondělí."""
    e = easter(year)
    return {date(year, m, d) for m, d in _FIXED} | {e - timedelta(days=2), e + timedelta(days=1)}


def is_holiday(day: date) -> bool:
    return day in cz_holidays(day.year)


def shops_closed(day: date) -> bool:
    """Mají velké obchody (nad 200 m²) ten den ze zákona celý den zavřeno?"""
    return (day.month, day.day) in _SHOPS_CLOSED or day == easter(day.year) + timedelta(days=1)


def shops_close_early(day: date) -> str | None:
    """Čas, kdy velké obchody ze zákona zavírají dřív (Štědrý den), jinak None."""
    return CHRISTMAS_EVE_CLOSE if (day.month, day.day) == (12, 24) else None
