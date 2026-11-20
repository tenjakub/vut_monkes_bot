"""Registrace commandů: na serveru beze změny, navíc globálně jen pro DM s botem (bez duplicit)."""

import asyncio
import importlib
import sys

import pytest

GUILD, BOT_DM = 0, 1


def _sent_payloads(monkeypatch, guild_ids: str):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    monkeypatch.setenv("GUILD_IDS", guild_ids)
    monkeypatch.setenv("BACKGROUND_REFRESH", "0")  # žádné stahování z internetu v testech
    for mod in ("config", "bot"):
        sys.modules.pop(mod, None)
    bot = importlib.import_module("bot")

    async def run():
        b = bot.ObedBot()
        sent = {}

        async def fake_sync(*, guild=None):
            cmds = b.tree.get_commands(guild=guild)
            sent[guild.id if guild else "global"] = [c.to_dict(b.tree) for c in cmds]
            return cmds

        async with b:
            b.tree.sync = fake_sync
            for ext in bot.EXTENSIONS:
                await b.load_extension(ext)
            await b.sync_commands()
            await b.fetcher.close()
        return sent

    try:
        return asyncio.run(run())
    finally:
        for mod in ("config", "bot"):
            sys.modules.pop(mod, None)


def test_guild_commands_unchanged_and_global_only_in_dm(monkeypatch):
    sent = _sent_payloads(monkeypatch, "111,222")
    assert set(sent) == {111, 222, "global"}
    names = {p["name"] for p in sent[111]}
    assert {"ppv", "mhd", "restaurace"} <= names
    # na serveru bez omezení kontextu, tak jako dřív
    assert all(p["contexts"] is None for p in sent[111] + sent[222])
    # globální sada jen pro DM s botem -> na serveru se neukáže podruhé
    assert {p["name"] for p in sent["global"]} == names
    assert all(p["contexts"] == [BOT_DM] for p in sent["global"])


def test_without_guild_ids_one_global_set_for_guild_and_dm(monkeypatch):
    sent = _sent_payloads(monkeypatch, "")
    assert set(sent) == {"global"}
    assert all(p["contexts"] == [GUILD, BOT_DM] for p in sent["global"])
