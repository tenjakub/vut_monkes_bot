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


@dataclass(frozen=True)
class Board:
    """Jedna "odjezdová tabule" – zastávka (všechna její nástupiště) a volitelný filtr."""

    key: str
    name: str  # přesný název zastávky v GTFS
    emoji: str
    color: int
    route_types: tuple[int, ...] | None = None  # 0 = tram, 3 = bus, 11 = trolejbus; None = vše
    note: str | None = None


BOARDS: dict[str, Board] = {
    b.key: b
    for b in [
        Board("technopark", "Technologický park", "🚋", 0x00CCFF, route_types=(0,), note="jen tramvaje"),
        Board("kolejni", "Kolejní", "🚌", 0x2C82C8),
    ]
}

# skupiny pro command a tlačítka
GROUPS: dict[str, tuple[str, ...]] = {
    "vse": tuple(BOARDS),
    **{k: (k,) for k in BOARDS},
}


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
