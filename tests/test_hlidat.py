"""🔔 Hlídání akcí: hledání v akcích, správa v /hlidat a soukromé zprávy o nových akcích."""

import asyncio
from datetime import date, timedelta
from types import SimpleNamespace

import discord
import pytest

from cogs import hlidat
from shops import kupi, watching
from storage import watches
from tests.fakes import Interaction, memory_db, with_values
from utils.text import parse_price

DAY = date(2026, 11, 20)


def run(coro):
    return asyncio.run(coro)


def deal(deal_id, product, price, shop="Lidl", amount="0.5 l", category="energeticke-a-iontove-napoje", days=4):
    return kupi.Deal(deal_id, product, amount, shop, price, 30, None, DAY + timedelta(days=days), category,
                     kupi.BASE, "", "")


DEALS = [
    deal("1", "Energetický nápoj Monster Energy Ultra", "29,90 Kč"),
    deal("2", "Energetický nápoj Monster Energy", "34,90 Kč", shop="BILLA"),
    deal("3", "Energetický nápoj Monster Energy", "24,90 Kč", shop="Kaufland"),  # obchod, který nesledujeme
    deal("4", "Energetický nápoj Monster Energy", "19,90 Kč", days=-1),  # už skončila
    deal("5", "Pivo Pilsner Urquell", "149,90 Kč", shop="Albert", amount="6x 0.5 l", category="pivo"),
    deal("6", "Pivo Pilsner Urquell", "149,90 Kč", shop="Albert supermarket", amount="6x 0.5 l", category="pivo"),
    deal("7", "Kuřecí prsní řízky", "129,90 Kč", category="drubez", amount="1 kg"),
]


@pytest.mark.parametrize(("text", "expected"), [("25", 25.0), ("25,90", 25.9), (" 30 Kč ", 30.0), ("", None)])
def test_parse_price(text, expected):
    assert parse_price(text) == expected


@pytest.mark.parametrize("text", ["levně", "0", "-5", "25 eur"])
def test_parse_price_nonsense(text):
    with pytest.raises(ValueError):
        parse_price(text)


def test_matches_words_price_and_shops():
    def ids(query, price=None):
        return [d.id for d in watching.matches(query, price, DEALS, DAY)]

    assert ids("monster") == ["1", "2"]  # jen naše obchody a platné, od nejlevnější
    assert ids("Monster", 30) == ["1"]
    assert ids("monster ultra") == ["1"]
    assert ids("Plzeň", 25) == ["5"]  # značka piva česky, cena za kus (149,90 / 6), Albert jen jednou
    assert ids("kureci prsa") == ["7"]  # bez diakritiky a začátek slova
    assert ids("x") == [] and ids("!!") == []


def _client(db, deals=DEALS, marks=None):
    slevy_cog = SimpleNamespace(shops=SimpleNamespace(all_deals=lambda: deals), marks=marks or {})
    return SimpleNamespace(db=db, get_cog=lambda name: slevy_cog if name == "Slevy" else None)


def _modal(query, price=""):
    modal = hlidat.WatchModal()
    modal.query._value, modal.price._value = query, price
    return modal


def test_add_shows_current_deals_and_remove(monkeypatch):
    monkeypatch.setattr(hlidat, "today", lambda: DAY)

    async def go():
        async with memory_db() as db:
            client = _client(db)
            opened = Interaction(client, user_id=5)
            await hlidat.Hlidat(client).hlidat.callback(hlidat.Hlidat(client), opened)
            add = Interaction(client, user_id=5)
            await _modal("Monster", "30").on_submit(add)
            bad = Interaction(client, user_id=5)
            await _modal("Monster", "hodně").on_submit(bad)
            mine = await watches.of_user(db, 5)
            known = await watches.known_deals(db, [mine[0].id])
            remove = Interaction(client, user_id=5)
            await with_values(hlidat.RemoveSelect(), str(mine[0].id)).callback(remove)
            other = Interaction(client, user_id=6)  # cizí hlídání zrušit nejde
            await with_values(hlidat.RemoveSelect(), str(mine[0].id)).callback(other)
            return opened.last(), add.last(), bad.last(), known, remove.last(), other.last(), await watches.of_user(db, 5)

    opened, added, bad, known, removed, other, left = run(go())
    assert "Zatím nic nehlídáš" in opened["content"] and opened["ephemeral"]
    assert added["content"].startswith("✅ Hlídám **Monster** do 30 Kč.\n**Teď v akci:**")
    assert "Monster Energy Ultra" in added["content"] and "· Lidl" in added["content"]
    assert "🔔 **Monster** do 30 Kč — teď 1 akce" in added["content"]
    assert len(known) == 1  # co je v akci teď, už zprávou nepřijde
    assert "nechápu" in bad["content"] and bad["ephemeral"]
    assert removed["content"].startswith("🗑️ Už nehlídám **Monster** do 30 Kč.")
    assert other["content"] == hlidat.STALE and left == []


class _User:
    def __init__(self, fail=None):
        self.sent = []
        self.fail = fail

    async def send(self, text, view=None):
        if self.fail:
            raise self.fail
        self.sent.append(text)


def _bot(db, users, deals):
    client = _client(db, deals)
    client.get_user = lambda user_id: users.get(user_id)
    return client


def test_notify_sends_new_deals_once(monkeypatch):
    monkeypatch.setattr(hlidat, "today", lambda: DAY)
    response = SimpleNamespace(status=403, reason="Forbidden")
    users = {1: _User(), 2: _User(fail=discord.Forbidden(response, "Cannot send messages to this user"))}

    async def go():
        async with memory_db() as db:
            now = hlidat.datetime.now(hlidat.TZ)
            await watches.add(db, 1, "monster", None, now)
            await watches.add(db, 1, "plzeň", 30, now)
            await watches.add(db, 2, "monster", None, now)
            cog = hlidat.Hlidat(_bot(db, users, DEALS[:2]))
            first = await cog.notify()
            again = await cog.notify()  # nic nového
            cog.bot = _bot(db, users, DEALS)  # přibyla akce na Plzeň
            third = await cog.notify()
            return first, again, third

    first, again, third = run(go())
    assert (first, again, third) == (2, 0, 1)
    text = users[1].sent[0]
    assert text.startswith("🔔 **Nové akce na to, co hlídáš**\n\n**monster** v akci\n")
    assert "Monster Energy Ultra" in text and "· BILLA" in text
    assert "**plzeň** do 30 Kč" in users[1].sent[1] and "Monster" not in users[1].sent[1]
