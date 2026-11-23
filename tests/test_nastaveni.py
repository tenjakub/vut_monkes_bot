"""⚙️ /nastaveni: nastavení serveru (od kolika lidí událost z /na-pivo) a jeho vliv na /na-pivo."""

import asyncio
from types import SimpleNamespace

import pytest

from cogs import napivo, nastaveni
from storage import settings
from tests.fakes import Interaction, memory_db, with_values
from tests.test_napivo import CREATED, TODAY, _click, _Guild, _Message
from utils.interactions import MessageState


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def empty_cache(monkeypatch):
    monkeypatch.setattr(settings, "_cache", {})


def test_defaults_without_anything_saved():
    assert settings.event_min_people(111) == 3
    assert settings.event_min_people(None) is None  # DM: žádný server, žádná událost


def test_admin_changes_threshold(monkeypatch):
    async def go():
        async with memory_db() as db:
            client = SimpleNamespace(db=db)
            cog = nastaveni.Nastaveni(client)
            opened = Interaction(client, user_id=9, guild=SimpleNamespace(id=111))
            await cog.nastaveni.callback(cog, opened)
            changed = Interaction(client, user_id=9, guild=SimpleNamespace(id=111))
            await with_values(nastaveni.EventSelect(), "0").callback(changed)
            other_server = settings.event_min_people(222)
            settings._cache.clear()
            await settings.load(db)  # po restartu bota
            return opened.last(), changed.last(), other_server, settings.event_min_people(111)

    opened, changed, other_server, after_restart = run(go())
    assert "**Události z /na-pivo:** od 3 lidí (výchozí)" in opened["content"] and opened["ephemeral"]
    assert changed["content"].startswith("✅ Uloženo.") and "**Události z /na-pivo:** nezakládat" in changed["content"]
    assert "Naposledy změnil(a) <@9>" in changed["content"]
    assert other_server == 3 and after_restart is None


def test_command_is_admin_only():
    command = nastaveni.Nastaveni.nastaveni
    assert command.default_permissions.manage_guild and command.extras["guild_only"]


def _meetup_with(going: int):
    answers = {i: "jdu" for i in range(1, going + 1)}
    return napivo.Meetup(TODAY, CREATED, "42", "19:00", "vlk", answers)


def test_na_pivo_follows_server_setting(monkeypatch):
    monkeypatch.setattr(napivo, "_now", lambda: CREATED.replace(hour=15))
    monkeypatch.setattr(napivo, "_state", MessageState())
    guild = _Guild()

    settings._cache[guild.id] = {settings.EVENT_MIN_PEOPLE: "0"}  # vypnuto
    msg = _click(_Message(1, napivo.meetup_embed(_meetup_with(4))), guild, 5)
    assert guild.created == [] and "bot založí" not in msg.embeds[0].description

    settings._cache[guild.id] = {settings.EVENT_MIN_PEOPLE: "2"}
    msg = _click(_Message(2, napivo.meetup_embed(_meetup_with(1))), guild, 2)
    assert len(guild.created) == 1

    hint = napivo.meetup_embed(_meetup_with(0), min_people=5).description
    assert "Když půjdou aspoň 5, bot založí na serveru událost." in hint
    assert "bot založí" not in napivo.meetup_embed(_meetup_with(0), min_people=None).description
