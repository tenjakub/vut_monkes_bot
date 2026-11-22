"""/kola: GBFS feed nextbike Brno (výřez stanic kolem kolejí uložený 22. 11. 2026) a výpis."""

import asyncio
import json
from pathlib import Path

import pytest

from bikes import nextbike
from bikes.service import AREAS, MAX_STATIONS, Bikes
from cogs import kola

FIX = Path(__file__).parent / "fixtures"


def read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class _FakeFetcher:
    def __init__(self, status: str | None = None) -> None:
        self.status = status or read("nextbike_status.json")
        self.calls: list[str] = []

    async def get(self, url, ttl, force=False):
        self.calls.append(url)
        if url == nextbike.STATIONS_URL:
            return read("nextbike_stations.json"), 1.0
        if url == nextbike.STATUS_URL:
            return self.status, 1.0
        raise ConnectionError(url)


def test_parse():
    stations = nextbike.parse_stations(read("nextbike_stations.json"))
    ppv = stations["642370607"]
    assert ppv.name == "VUT - Koleje a menzy (Pod Palackého vrchem)"
    assert ppv.url == "https://nxtb.it/p/642370607"
    status, updated = nextbike.parse_status(read("nextbike_status.json"))
    assert status["642370607"] == (1, True) and updated > 0


def test_nearby_sorted_and_within_radius():
    stations = nextbike.parse_stations(read("nextbike_stations.json"))
    status, _ = nextbike.parse_status(read("nextbike_status.json"))
    area = AREAS["ppv"]
    near = nextbike.nearby(stations, status, area.lat, area.lon, area.radius)
    assert near and all(n.distance <= area.radius for n in near)
    assert [n.distance for n in near] == sorted(n.distance for n in near)
    assert "Náměstí 28. dubna - ZOO" not in {n.station.name for n in near}  # daleko


@pytest.mark.parametrize(("n", "text"), [(0, "0 kol"), (1, "1 kolo"), (3, "3 kola"), (5, "5 kol")])
def test_bikes_text(n, text):
    assert kola.bikes_text(n) == text


def test_build_message():
    fetcher = _FakeFetcher()
    content, embeds, view = asyncio.run(kola.build_message(Bikes(fetcher), "ppv"))
    assert content.startswith("### 🚲 Kola u PPV")
    assert "🚲 **19 kol** na 7 stanicích" in content
    (embed,) = embeds
    cards = [f for f in embed.fields if f.name != "​"]
    assert 0 < len(cards) <= MAX_STATIONS
    assert cards[0].name == "Fakulta podnikatelská"  # bez „VUT - “
    assert cards[0].value.startswith("[🚲 **2 kola**](https://nxtb.it/p/642370496)")
    ids = [c.custom_id for c in view.children if getattr(c, "custom_id", None)]
    assert ids == ["kola:ppv:g", "kola:purkyne:g", "kola:fit:g", "kola:ppv:r"]


def test_parsed_once_per_download():
    fetcher = _FakeFetcher()
    bikes = Bikes(fetcher)
    asyncio.run(bikes.snapshot("ppv"))
    first = bikes._status
    asyncio.run(bikes.snapshot("fit"))
    assert bikes._status is first  # stejná stažená data -> neparsuje se znovu


def test_no_bikes_nearby_shows_nearest_further():
    raw = json.loads(read("nextbike_status.json"))
    for s in raw["data"]["stations"]:
        if s["station_id"] != "28142364":  # kola jen u ZOO
            s["num_bikes_available"] = 0
    fetcher = _FakeFetcher(json.dumps(raw))
    content, embeds, _ = asyncio.run(kola.build_message(Bikes(fetcher), "ppv"))
    assert "V okolí teď není žádné volné kolo" in content
    nearest = embeds[0].fields[-1]
    assert nearest.name == "👀 Nejbližší kolo dál" and "ZOO" in nearest.value
