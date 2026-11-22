"""/otevreno: otevírací doby KaM a obchodů, stav „teď otevřeno“, svátky."""

import asyncio
from datetime import date, datetime
from pathlib import Path

import pytest

from cogs import otevreno
from lunch import kam, service
from shops import kupi
from utils import holidays, opening
from utils.opening import State

FIX = Path(__file__).parent / "fixtures"
TZ = service.TZ


def read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


def at(day: date, hm: str) -> datetime:
    h, m = map(int, hm.split(":"))
    return datetime(day.year, day.month, day.day, h, m, tzinfo=TZ)


MONDAY = date(2026, 11, 23)


def test_parse_overview():
    provozy = {p.name: p for p in kam.parse_overview(read("kam_otdo.html"))}
    assert "Caffe Bar Piccolo" in provozy  # hvězdičky z poznámky pod čarou pryč
    purkynova = provozy["Menza Purkyňova"]
    assert purkynova.address == "Purkyňova 93, Brno-Královo Pole"
    assert purkynova.intervals(MONDAY) == [("11:00", "14:30"), ("17:00", "20:00")]
    assert purkynova.hours_text(MONDAY) == "11:00–14:30, 17:00–20:00"


def test_food_spots_skip_staff_and_out_of_service():
    names = [s.name for s in otevreno.food_spots(kam.parse_overview(read("kam_otdo.html")), MONDAY)]
    assert "Menza Kolejní" in names and "Bufet FEKT" in names
    assert not any("aměstnan" in n for n in names)  # jen pro zaměstnance
    assert "Caffe Bar Piccolo" not in names  # žádná otevírací doba = mimo provoz


@pytest.mark.parametrize(
    ("hm", "state", "at_hm"),
    [
        ("10:00", State.LATER, "11:00"),
        ("12:00", State.OPEN, "14:30"),
        ("14:10", State.CLOSING_SOON, "14:30"),
        ("15:00", State.LATER, "17:00"),  # mezi obědem a večeří
        ("19:45", State.CLOSING_SOON, "20:00"),
        ("20:00", State.CLOSED, None),
    ],
)
def test_status(hm, state, at_hm):
    s = opening.status(at(MONDAY, hm), [("11:00", "14:30"), ("17:00", "20:00")], [("11:00", "14:00")])
    assert s.state is state
    assert (f"{s.at:%H:%M}" if s.at else None) == at_hm
    if state is State.CLOSED:
        assert s.tomorrow == "11:00–14:00"


def test_status_over_midnight():
    s = opening.status(at(MONDAY, "23:30"), [("7:00", "0:00")], [])
    assert s.state is State.CLOSING_SOON and s.at == at(date(2026, 11, 24), "0:00")
    assert opening.status(at(MONDAY, "12:00"), [], []).tomorrow == "zavřeno"


def test_shop_holidays():
    assert holidays.shops_closed(date(2026, 12, 25)) and holidays.shops_closed(date(2026, 4, 6))  # Velikonoční pondělí
    assert not holidays.shops_closed(date(2026, 11, 17))  # 17. listopadu mají obchody otevřeno
    assert not holidays.shops_closed(date(2026, 4, 3))  # Velký pátek taky
    assert holidays.shops_close_early(date(2026, 12, 24)) == "12:00"


def test_shop_intervals_respect_holidays():
    page = kupi.parse_store(read("kupi_lidl_kralovo_pole.html"), MONDAY)
    assert otevreno.shop_intervals(page, MONDAY) == ([("7:00", "21:00")], None)
    assert otevreno.shop_intervals(page, date(2026, 12, 25)) == ([], "svátek")
    assert otevreno.shop_intervals(page, date(2026, 12, 24)) == ([("7:00", "12:00")], "Štědrý den")


class _FakeFetcher:
    async def get(self, url, ttl, force=False):
        assert url == kam.OVERVIEW_URL
        return read("kam_otdo.html"), 1.0


class _FakeShops:
    async def store_pages(self, force=False):
        page = kupi.parse_store(read("kupi_billa_srbska.html"), MONDAY)
        return {"billa/billa-brno-srbska": page, "lidl/lidl-brno-kralovo-pole": None}


def test_build_message():
    content, embeds, view = asyncio.run(otevreno.build_message(_FakeFetcher(), _FakeShops(), now=at(MONDAY, "14:10")))
    assert content.startswith("### 🕐 Co je otevřeno – pondělí 23. 11.")
    food, shops = embeds
    assert len({e.url for e in embeds}) == len(embeds)  # stejná URL = Discord embedy sloučí
    assert sum(len(e) for e in embeds) < 6000
    # otevřené napřed, zavřené (Menza FCH zavírá ve 14:00) na konci
    assert food.fields[0].value.startswith(("🟢", "🟡"))
    fch = next(f for f in food.fields if f.name.endswith("Menza FCH"))
    assert fch.value.startswith("🔴 zavřeno") and "zítra 11:00–14:00" in fch.value
    assert [f.name for f in shops.fields if f.name.strip("​")] == ["🛒 BILLA Srbská"]  # Lidl se nenačetl


def test_build_message_survives_errors():
    class Broken:
        async def get(self, *a, **k):
            raise ConnectionError

        async def store_pages(self, force=False):
            raise ConnectionError

    _, embeds, _ = asyncio.run(otevreno.build_message(Broken(), Broken(), now=at(MONDAY, "12:00")))
    assert all(e.description.startswith("⚠️") for e in embeds)
