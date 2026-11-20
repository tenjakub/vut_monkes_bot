"""Správa dat MHD: stažení/obnova jízdního řádu na disk a výluky z realtime feedu."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from lunch.fetcher import Fetcher

from . import alerts, gtfs

log = logging.getLogger(__name__)

GTFS_URL = "https://kordis-jmk.cz/gtfs/gtfs.zip"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GTFS_MAX_AGE = 12 * 3600  # KORDIS jízdní řád přegenerovává denně ráno
ALERTS_TTL = 5 * 60


TRAM = (0,)
BUS = (3, 11, 800)  # autobusy i trolejbusy


@dataclass(frozen=True)
class Board:
    """Jedna "odjezdová tabule" – zastávka (nebo jen některá její nástupiště) a jak ji zobrazit.

    layout:
      "merge" – jedna kartička na směr (nástupiště) pro všechny linky: "Tram → Centrum",
                u každého času číslo linky (Technologický park, Červinkova).
      "lines" – kartička pro každou linku. Nejčastější konečná je v nadpisu, jiné konečné
                jsou jen značka za časem (Skácelova).
      "auto"  – kartička podle linky a cíle, s chytrostmi níže (Kolejní).
    """

    key: str
    name: str  # přesný název zastávky v GTFS
    emoji: str
    color: int
    route_types: tuple[int, ...] | None = None  # 0 = tram, 3 = bus, 11 = trolejbus; None = vše
    note: str | None = None
    layout: str = "auto"
    title: str | None = None  # nadpis embedu a tlačítka, pokud se liší od názvu zastávky
    platforms: tuple[str, ...] | None = None  # jen tato nástupiště (stop_id); None = všechna
    # "merge": popisek směru pro nástupiště (stop_id -> "Centrum"); jinak obvyklá konečná
    directions: tuple[tuple[str, str], ...] = ()
    vehicle: str = "Tram"  # "merge": slovo v nadpisu kartičky ("Tram → Centrum")
    # "auto": linky sloučené do jedné kartičky bez ohledu na cíl
    merged_lines: tuple[str, ...] = ()
    # "auto": spoje, které na konečné pokračují dál, dostanou kartičku "linka → směr" a jsou vždy první
    continuing: tuple[tuple[str, str], ...] = ()

    @property
    def label(self) -> str:
        return self.title or self.name


# ID nástupišť jsou stabilní ID z jízdního řádu IDS JMK (U<zastávka>Z<nástupiště>)
BOARDS: dict[str, Board] = {
    b.key: b
    for b in [
        Board(
            "technopark", "Technologický park", "🚋", 0x00CCFF,
            route_types=TRAM, note="tramvaje", layout="merge",
            directions=(("U1659Z2", "Centrum"),),
        ),
        Board(
            "kolejni", "Kolejní", "🚌", 0x2C82C8,
            merged_lines=("65",),  # Řečkovice, hřbitov / nádraží – je to jedno
            continuing=(("72", "Semilasso"),),  # z Technoparku jede dál přes Skácelovu a Semilasso
        ),
        Board(
            "cervinkova", "Červinkova", "🚋", 0x15AABF,
            route_types=TRAM, note="tramvaje", layout="merge",
            directions=(("U1072Z1", "Technologický park"), ("U1072Z2", "Centrum")),
        ),
        Board(
            "skacelova_vychod", "Skácelova", "🚎", 0x5C7CFA,
            title="Skácelova → východ", platforms=("U1567Z6",),
            route_types=BUS, note="autobusy a trolejbusy, další zastávka Slovanské náměstí", layout="lines",
        ),
        Board(
            "skacelova_zapad", "Skácelova", "🚎", 0x845EF7,
            title="Skácelova → západ", platforms=("U1567Z5",),
            route_types=BUS, note="autobusy a trolejbusy, další zastávka Záhřebská", layout="lines",
        ),
    ]
}

# Oblasti = co ukazuje jeden command (klíč "vse" zůstává kvůli tlačítkům na starších zprávách)
AREAS: dict[str, tuple[str, tuple[str, ...]]] = {
    "vse": ("PPV", ("technopark", "kolejni")),  # koleje Pod Palackého vrchem
    "purkyne": ("Purkyně", ("cervinkova", "skacelova_vychod", "skacelova_zapad")),
}

# skupiny pro command a tlačítka: celé oblasti i jednotlivé zastávky
GROUPS: dict[str, tuple[str, ...]] = {
    **{k: boards for k, (_, boards) in AREAS.items()},
    **{k: (k,) for k in BOARDS},
}


def area_of(group: str) -> str:
    if group in AREAS:
        return group
    return next(a for a, (_, boards) in AREAS.items() if group in boards)


class Transit:
    def __init__(self, fetcher: Fetcher, data_dir: Path = DATA_DIR) -> None:
        self.fetcher = fetcher
        self.path = data_dir / "gtfs.zip"
        self._timetable: gtfs.Timetable | None = None
        self._loaded_mtime: float | None = None
        self._lock = asyncio.Lock()

    def _file_age(self) -> float | None:
        if not self.path.exists():
            return None
        return time.time() - self.path.stat().st_mtime

    async def refresh(self, force: bool = False) -> gtfs.Timetable:
        """Zajistí čerstvý jízdní řád: stáhne nový zip, pokud je starý, a načte ho."""
        async with self._lock:
            age = self._file_age()
            if force or age is None or age > GTFS_MAX_AGE:
                try:
                    await self.fetcher.download(GTFS_URL, self.path)
                except Exception:
                    if not self.path.exists():
                        raise
                    log.exception("Stažení GTFS selhalo, používám starší soubor")
            mtime = self.path.stat().st_mtime
            if self._timetable is None or self._loaded_mtime != mtime:
                names = [b.name for b in BOARDS.values()]
                started = time.monotonic()
                self._timetable = await asyncio.to_thread(gtfs.load, self.path, names)
                self._loaded_mtime = mtime
                log.info("GTFS načten za %.1f s", time.monotonic() - started)
            return self._timetable

    async def timetable(self) -> gtfs.Timetable:
        age = self._file_age()
        if self._timetable is not None and age is not None and age <= GTFS_MAX_AGE:
            return self._timetable
        return await self.refresh()

    async def alerts(self, force: bool = False) -> list[alerts.Alert]:
        data, _ = await self.fetcher.get_bytes(alerts.URL, ttl=ALERTS_TTL, force=force)
        return await asyncio.to_thread(alerts.parse, data)
