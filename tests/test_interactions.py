"""utils.interactions: hláška při chybě tlačítka a stav hlasovacích zpráv."""

import asyncio

import discord

from utils.interactions import MessageState, reported


class _Response:
    def __init__(self, done=False):
        self.done = done
        self.sent = []

    def is_done(self):
        return self.done

    async def send_message(self, text, ephemeral=False):
        self.sent.append((text, ephemeral))


class _Followup:
    def __init__(self):
        self.sent = []

    async def send(self, text, ephemeral=False):
        self.sent.append((text, ephemeral))


class _Interaction:
    def __init__(self, done=False):
        self.response = _Response(done)
        self.followup = _Followup()


class _Button:
    @reported
    async def callback(self, interaction):
        raise RuntimeError("rozbitý zdroj")


def test_reported_tells_user(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "x")
    fresh, deferred = _Interaction(), _Interaction(done=True)
    asyncio.run(_Button().callback(fresh))
    asyncio.run(_Button().callback(deferred))
    (text, ephemeral), = fresh.response.sent
    assert text.startswith("Něco se pokazilo") and ephemeral
    assert deferred.followup.sent and not deferred.response.sent  # po defer() už jen followup


def test_message_state_is_bounded_and_remembers():
    state = MessageState(size=2)
    for i in range(5):
        state.lock(i)
        state.remember(i, discord.Embed(title=str(i)))
    assert len(state._locks) == 2 and len(state._embeds) == 2
    msg = type("M", (), {"id": 4, "embeds": [discord.Embed(title="stará")]})()
    assert state.embed(msg).title == "4"
    old = type("M", (), {"id": 0, "embeds": [discord.Embed(title="ze zprávy")]})()
    assert state.embed(old).title == "ze zprávy"
    assert state.lock(9) is state.lock(9)
