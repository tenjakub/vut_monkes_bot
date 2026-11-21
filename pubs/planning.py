"""Hledání společného termínu na pivo (/na-pivo-termin) – čistá logika bez Discordu.

Hlasy: {user_id: {den: čas "HH:MM" nebo None}}. Čas znamená „můžu od“, None = kdykoliv.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

PLAN_DAYS = 14  # dva týdny dopředu včetně dneška
WEEKDAYS_SHORT = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]

Votes = dict[int, dict[date, str | None]]


def plan_days(start: date) -> list[date]:
    return [start + timedelta(days=i) for i in range(PLAN_DAYS)]


def day_label(d: date) -> str:
    """'So 22. 11.'"""
    return f"{WEEKDAYS_SHORT[d.weekday()]} {d.day}. {d.month}."


def common_time(times: list[str | None]) -> str | None:
    """Od kdy můžou všichni: nejpozdější z „můžu od“ (kdykoliv se nepočítá). Všichni kdykoliv -> None."""
    known = [t for t in times if t]
    return max(known, key=lambda t: tuple(int(x) for x in t.split(":"))) if known else None


def by_day(votes: Votes) -> dict[date, dict[int, str | None]]:
    days: dict[date, dict[int, str | None]] = {}
    for user, choices in votes.items():
        for d, time in choices.items():
            days.setdefault(d, {})[user] = time
    return dict(sorted(days.items()))


@dataclass(frozen=True)
class Best:
    day: date
    users: list[int]
    time: str | None  # od kdy můžou všichni, None = kdykoliv


def best_day(votes: Votes, today: date) -> Best | None:
    """Den (dnes a dál), kdy může nejvíc lidí; při shodě ten dřívější."""
    best: Best | None = None
    for d, people in by_day(votes).items():
        if d < today or not people:
            continue
        if best is None or len(people) > len(best.users):
            best = Best(d, list(people), common_time(list(people.values())))
    return best


def resolve_date(day: int, month: int, ref: date) -> date | None:
    """Den a měsíc z nadpisu -> datum nejblíž po `ref` (dni založení), i přes Nový rok."""
    for year in (ref.year, ref.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if d >= ref - timedelta(days=1):
            return d
    return None
