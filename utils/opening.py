"""Je teď otevřeno? Stav podniku podle otevírací doby (intervaly "od–do" na dnešek a zítřek). Bez discord.py."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum

Interval = tuple[str, str]  # ("11:00", "14:30")

CLOSING_SOON = timedelta(minutes=30)
_INTERVAL_RE = re.compile(r"(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})")


class State(Enum):
    OPEN = "open"
    CLOSING_SOON = "closing"  # zavírá do CLOSING_SOON
    LATER = "later"  # dnes ještě otevře
    CLOSED = "closed"  # dnes už ne


@dataclass(frozen=True)
class Status:
    state: State
    at: datetime | None = None  # OPEN/CLOSING_SOON: kdy zavře, LATER: kdy otevře
    tomorrow: str = ""  # "11:00–14:30" / "zavřeno" – u CLOSED, ať je vidět, kdy příště

    @property
    def is_open(self) -> bool:
        return self.state in (State.OPEN, State.CLOSING_SOON)


def parse_intervals(text: str | None) -> list[Interval]:
    """'07:00–21:00' / '11:00 – 14:30 17:00 – 20:00' -> [("07:00", "21:00"), …]."""
    return _INTERVAL_RE.findall(text or "")


def intervals_text(intervals: list[Interval]) -> str:
    return ", ".join(f"{a}–{b}" for a, b in intervals) or "zavřeno"


def minutes(hm: str) -> int:
    """'7:30' -> 450 (minut od půlnoci), pro porovnávání časů."""
    h, m = map(int, hm.split(":"))
    return h * 60 + m


def _at(day: date, hm: str, tz) -> datetime:
    """'14:30' v daný den; '24:00' (a '0:00' jako konec) = půlnoc na konci dne."""
    return datetime.combine(day, time(0), tz) + timedelta(minutes=minutes(hm))


def status(now: datetime, today: list[Interval], tomorrow: list[Interval]) -> Status:
    """Stav podniku v čase `now` (s časovou zónou) podle dnešních a zítřejších intervalů."""
    day, tz = now.date(), now.tzinfo
    for start, end in today:
        opens, closes = _at(day, start, tz), _at(day, end, tz)
        if closes <= opens:  # "22:00–02:00" nebo "07:00–0:00" = přes půlnoc
            closes += timedelta(days=1)
        if opens <= now < closes:
            soon = closes - now <= CLOSING_SOON
            return Status(State.CLOSING_SOON if soon else State.OPEN, closes)
        if now < opens:
            return Status(State.LATER, opens)
    return Status(State.CLOSED, tomorrow=intervals_text(tomorrow))
