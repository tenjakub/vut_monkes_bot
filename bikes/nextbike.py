"""Sdílená kola nextbike Brno z otevřeného GBFS feedu (licence CC0-1.0). Bez discord.py.

Feed: https://gbfs.nextbike.net/maps/gbfs/v2/nextbike_te/gbfs.json
- station_information = stanice (název, poloha, odkaz do aplikace), mění se zřídka
- station_status = kolik kol na které stanici je teď (feed má ttl 60 s)
Kola mimo stanice (free_bike_status) se neberou, v Brně jich je jen pár.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass

SYSTEM = "nextbike_te"  # nextbike Brno
BASE = f"https://gbfs.nextbike.net/maps/gbfs/v2/{SYSTEM}/cs"
STATIONS_URL = f"{BASE}/station_information.json"
STATUS_URL = f"{BASE}/station_status.json"
SOURCE_URL = "https://nextbikeczech.com/mesto/brno/"

WALK_SPEED = 75  # m/min – chůze, pro „🚶 3 min“ (vzdušnou čarou, takže spíš optimisticky)


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    lat: float
    lon: float
    url: str  # odkaz na stanici (otevře aplikaci nextbike / web)


@dataclass(frozen=True)
class Nearby:
    station: Station
    distance: float  # m vzdušnou čarou
    bikes: int
    renting: bool = True  # půjčuje stanice teď kola?

    @property
    def walk_minutes(self) -> int:
        return max(1, round(self.distance / WALK_SPEED))


def parse_stations(text: str) -> dict[str, Station]:
    data = json.loads(text)["data"]["stations"]
    stations = {}
    for s in data:
        sid = str(s["station_id"])
        url = (s.get("rental_uris") or {}).get("web") or f"https://nxtb.it/p/{sid}"
        stations[sid] = Station(sid, s["name"].strip(), float(s["lat"]), float(s["lon"]), url)
    return stations


def parse_status(text: str) -> tuple[dict[str, tuple[int, bool]], int]:
    """({station_id: (počet kol k půjčení, půjčuje?)}, unix čas aktualizace feedu). Neinstalované stanice vynechá."""
    raw = json.loads(text)
    status = {}
    for s in raw["data"]["stations"]:
        if not s.get("is_installed", True):
            continue
        status[str(s["station_id"])] = (int(s.get("num_bikes_available", 0)), bool(s.get("is_renting", True)))
    return status, int(raw.get("last_updated", 0))


def distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Vzdálenost v metrech (na pár kilometrů stačí rovinná aproximace)."""
    dy = math.radians(lat2 - lat1)
    dx = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return 6_371_000 * math.hypot(dx, dy)


def nearby(
    stations: dict[str, Station], status: dict[str, tuple[int, bool]], lat: float, lon: float, radius: float
) -> list[Nearby]:
    """Stanice do `radius` metrů od místa, od nejbližší. Stanice bez stavu (neinstalované) se vynechají."""
    result = []
    for sid, st in stations.items():
        if sid not in status:
            continue
        d = distance(lat, lon, st.lat, st.lon)
        if d <= radius:
            bikes, renting = status[sid]
            result.append(Nearby(st, d, bikes if renting else 0, renting))
    return sorted(result, key=lambda n: n.distance)


def nearest_with_bikes(
    stations: dict[str, Station], status: dict[str, tuple[int, bool]], lat: float, lon: float
) -> Nearby | None:
    """Nejbližší stanice, kde se teď dá půjčit kolo (když v okolí žádné není)."""
    return next((n for n in nearby(stations, status, lat, lon, math.inf) if n.bikes > 0), None)
