"""Historie cen akcí (storage/prices.py) a 🔥/🎣 u slev."""

import asyncio
from datetime import date, timedelta

from cogs import slevy
from shops import kupi
from shops.service import DealsResult
from storage import prices
from tests.fakes import memory_db

DAY = date(2026, 11, 20)


def run(coro):
    return asyncio.run(coro)


def kozel(deal_id: str, price: str, percent: int | None = 30, shop: str = "BILLA", amount: str = "0.5 l") -> kupi.Deal:
    liters = 0.5 if amount == "0.5 l" else 3.0
    per_liter = float(price.split()[0].replace(",", ".")) / liters
    return kupi.Deal(
        deal_id, "Pivo světlý ležák 11° Medium Velkopopovický Kozel", amount, shop, price, percent,
        None, DAY + timedelta(days=4), "pivo", f"{kupi.BASE}/sleva/pivo-kozel-11", "",
        f"{per_liter:.2f} Kč / 1 l".replace(".", ","),
    )


async def _history(db, weeks: list[str]) -> None:
    """Akce z minulých týdnů: každá jiné ID, cena za stejné balení."""
    for i, price in enumerate(weeks):
        await prices.record(db, [kozel(f"old{i}", price)], DAY - timedelta(days=7 * (len(weeks) - i)))


def test_record_is_one_row_per_deal():
    async def go():
        async with memory_db() as db:
            await prices.record(db, [kozel("a", "15,90 Kč")], DAY)
            await prices.record(db, [kozel("a", "15,90 Kč")], DAY + timedelta(days=1))  # další den ta samá akce
            return [tuple(r) for r in await db.fetchall("SELECT product, price, unit_price, first_seen, last_seen FROM deal_price")]

    assert run(go()) == [("pivo-kozel-11", 15.9, 31.8, "2026-11-20", "2026-11-21")]


def test_marks_hot_bait_and_not_enough_data():
    async def go():
        async with memory_db() as db:
            await _history(db, ["15,90 Kč", "16,90 Kč", "15,90 Kč", "17,90 Kč"])
            today = [
                kozel("hot", "13,90 Kč"),  # nejlevnější, co jsme viděli
                kozel("bait", "19,90 Kč", shop="Lidl"),  # „−30 %“, ale v akci bývá za 16 Kč
                kozel("normal", "15,90 Kč", shop="Albert"),  # obvyklá akční cena
                kozel("pack", "89,90 Kč", amount="6x 0.5 l"),  # jiné balení, historii nemá
            ]
            await prices.record(db, today, DAY)
            return await prices.marks(db, today, DAY)

    assert run(go()) == {"hot": prices.HOT, "bait": prices.BAIT}


def test_same_price_every_week_is_not_hot():
    async def go():
        async with memory_db() as db:
            await _history(db, ["15,90 Kč"] * 4)
            return await prices.marks(db, [kozel("now", "15,90 Kč")], DAY)

    assert run(go()) == {}


def test_beer_line_and_legend_show_marks(monkeypatch):
    monkeypatch.setattr(slevy, "today", lambda: DAY)
    deals = [kozel("hot", "13,90 Kč"), kozel("bait", "19,90 Kč", shop="Lidl")]

    class FakeShops:
        async def beer_deals(self, force=False):
            return DealsResult(deals=deals, fetched_at=0.0)

    marks = {"hot": prices.HOT, "bait": prices.BAIT}
    content, embeds, _ = run(slevy.build_message(FakeShops(), slevy.VIEW_BEER, marks=marks))
    billa = next(e for e in embeds if "BILLA" in e.title)
    assert "**13,90 Kč** 🔥 ·" in billa.description
    assert "🔥 nejlevnější" in content and "🎣 sleva jen na oko" in content
    plain, _, _ = run(slevy.build_message(FakeShops(), slevy.VIEW_BEER))
    assert "🔥" not in plain and "🎣" not in plain
