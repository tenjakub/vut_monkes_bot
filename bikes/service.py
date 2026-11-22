"""Kola nextbike u kolejí a FITu: oblasti, stahování a naparsovaná data v paměti."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from lunch.fetcher import Fetcher

from . import nextbike

REFRESH_MINUTES = 3  # obnova stavu stanic na pozadí
STATUS_TTL = 4 * 60  # delší než interval obnovy, ať command nestahuje sám
STATIONS_TTL = 12 * 60 * 60  # seznam stanic se mění zřídka


@dataclass(frozen=True)
class Area:
    key: str
    label: str  # "u PPV" – do nadpisu
    button: str  # "PPV" – na tlačítko
    lat: float
    lon: float
    radius: float  # m – stanice v okolí


# Klíče oblastí jsou v custom_id tlačítek (kola:<oblast>:…), nepřejmenovávat.
AREAS: dict[str, Area] = {
    a.key: a
    for a in [
        # koleje Pod Palackého vrchem (Kolejní 2) – stanic je tu víc: koleje, fakulty, CEITEC, Technopark
        Area("ppv", "u PPV", "PPV", 49.2310, 16.5725, 800),
        Area("purkyne", "u Purkyní", "Purkyně", 49.2238, 16.5838, 700),
        Area("fit", "u FITu", "FIT", 49.2266, 16.5965, 500),
    ]
}
MAX_STATIONS = 9


@dataclass
class Snapshot:
    area: Area
    stations: list[nextbike.Nearby]
    updated: int  # unix čas dat z feedu
    nearest: nextbike.Nearby | None = None  # nejbližší kolo dál, když v okolí žádné není

    @property
    def total(self) -> int:
        return sum(n.bikes for n in self.stations)


class Bikes:
    """Stav stanic nextbike. Parsuje se jen po novém stažení, commandy berou hotová data."""

    def __init__(self, fetcher: Fetcher) -> None:
        self.fetcher = fetcher
        self._stations: tuple[float, dict[str, nextbike.Station]] | None = None
        self._status: tuple[float, tuple[dict[str, tuple[int, bool]], int]] | None = None

    async def _load(self, force: bool):
        text, fetched = await self.fetcher.get(nextbike.STATIONS_URL, ttl=STATIONS_TTL)
        if self._stations is None or self._stations[0] != fetched:
            self._stations = (fetched, await asyncio.to_thread(nextbike.parse_stations, text))
        text, fetched = await self.fetcher.get(nextbike.STATUS_URL, ttl=STATUS_TTL, force=force)
        if self._status is None or self._status[0] != fetched:
            self._status = (fetched, await asyncio.to_thread(nextbike.parse_status, text))
        return self._stations[1], *self._status[1]

    async def refresh(self) -> None:
        await self._load(force=True)

    async def snapshot(self, area_key: str, force: bool = False) -> Snapshot:
        area = AREAS[area_key]
        stations, status, updated = await self._load(force)
        near = nextbike.nearby(stations, status, area.lat, area.lon, area.radius)
        # nejvíc MAX_STATIONS nejbližších, ale stanici s koly radši než prázdnou na kraji okolí
        if len(near) > MAX_STATIONS:
            keep = sorted(near, key=lambda n: (n.bikes == 0, n.distance))[:MAX_STATIONS]
            near = sorted(keep, key=lambda n: n.distance)
        snap = Snapshot(area, near, updated)
        if snap.total == 0:
            snap.nearest = nextbike.nearest_with_bikes(stations, status, area.lat, area.lon)
        return snap
