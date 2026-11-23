"""🏠 /koleje: výchozí koleje člověka a /mhd a /kola, které podle nich rovnou ukážou správné koleje."""

import asyncio
from types import SimpleNamespace

from cogs import kola, koleje, mhd
from storage import Database, prefs
from tests.fakes import Interaction, memory_db


def run(coro):
    return asyncio.run(coro)


def test_choose_and_clear_dorm():
    async def go():
        async with memory_db() as db:
            client = SimpleNamespace(db=db)
            cog = koleje.Koleje(client)
            opened = Interaction(client, user_id=3)
            await cog.koleje.callback(cog, opened)
            chose = Interaction(client, user_id=3)
            await koleje.DormButton("purkyne").callback(chose)
            stored = await prefs.dorm(db, 3)
            other = await prefs.dorm(db, 4)  # jiným se nic nemění
            cleared = Interaction(client, user_id=3)
            await koleje.DormButton(koleje.UNDECIDED).callback(cleared)
            rows = await db.fetchall("SELECT * FROM user_setting")
            return opened.last(), chose.last(), stored, other, rows

    opened, chose, stored, other, rows = run(go())
    assert "Teď: 🤷 **Nerozhodnuto**" in opened["content"] and opened["ephemeral"]
    assert chose["content"].startswith("✅ Uloženo.") and "Teď: 🏢 **Purkyně**" in chose["content"]
    disabled = [b.item.label for b in chose["view"].children if b.item.disabled]
    assert disabled == ["Purkyně"]
    assert (stored, other) == ("purkyne", None)
    assert rows == []  # nerozhodnuto = žádný záznam


def test_dorm_without_database_is_undecided():
    assert run(prefs.dorm(None, 1)) is None
    assert run(prefs.dorm(Database(":memory:"), 1)) is None


def test_mhd_and_kola_open_users_dorm(monkeypatch):
    shown = {}

    async def mhd_send(self, interaction, group):
        shown.setdefault("mhd", []).append(group)

    async def kola_build(bikes, area, force=False):
        shown.setdefault("kola", []).append(area)
        return "", [], None

    monkeypatch.setattr(mhd.Mhd, "_send", mhd_send)
    monkeypatch.setattr(kola, "build_message", kola_build)

    async def go():
        async with memory_db() as db:
            await prefs.put(db, 1, prefs.DORM, "purkyne")
            bot = SimpleNamespace(db=db)
            mhd_cog = mhd.Mhd.__new__(mhd.Mhd)
            mhd_cog.bot = bot
            kola_cog = kola.Kola.__new__(kola.Kola)
            kola_cog.bot, kola_cog.bikes = bot, None
            for user in (1, 2):  # 1 = Purkyně, 2 = nerozhodnuto
                await mhd.Mhd.mhd.callback(mhd_cog, Interaction(bot, user_id=user))
                await kola.Kola.kola.callback(kola_cog, Interaction(bot, user_id=user))
            await mhd.Mhd.mhd.callback(mhd_cog, Interaction(bot, user_id=1), "technopark")  # výslovná volba vyhrává

    run(go())
    assert shown == {"mhd": ["purkyne", "vse", "technopark"], "kola": ["purkyne", "ppv"]}
