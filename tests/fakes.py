"""Falešná interakce pro testy tlačítek a commandů: zaznamená, co by bot poslal, nic neposílá na Discord."""

from __future__ import annotations

import contextlib
from types import SimpleNamespace

from storage import Database


class Response:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []  # (metoda, argumenty)
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def _record(self, kind, *args, **kwargs):
        if args:
            kwargs["content"] = args[0]
        self.calls.append((kind, kwargs))
        self._done = True

    async def defer(self, **kwargs):
        await self._record("defer", **kwargs)

    async def send_message(self, *args, **kwargs):
        await self._record("send", *args, **kwargs)

    async def edit_message(self, *args, **kwargs):
        await self._record("edit", *args, **kwargs)

    async def send_modal(self, modal):
        await self._record("modal", modal=modal)


class Followup:
    def __init__(self):
        self.sent: list[dict] = []

    async def send(self, *args, **kwargs):
        if args:
            kwargs["content"] = args[0]
        self.sent.append(kwargs)


class Interaction:
    def __init__(self, client, user_id: int = 1, guild=None, permissions=None):
        self.client = client
        self.user = SimpleNamespace(id=user_id, mention=f"<@{user_id}>", display_name=f"user{user_id}")
        self.guild = guild
        self.guild_id = getattr(guild, "id", None)
        self.permissions = permissions
        self.response = Response()
        self.followup = Followup()
        self.edited: list[dict] = []

    async def edit_original_response(self, **kwargs):
        self.edited.append(kwargs)

    def last(self) -> dict:
        """Poslední odpověď (zpráva, úprava nebo followup)."""
        if self.followup.sent:
            return self.followup.sent[-1]
        return self.response.calls[-1][1]


def with_values(item, *values):
    """Nastaví vybrané hodnoty výběru (jako by uživatel vybral)."""
    item.item._values = list(values)  # discord.ui.Select.values čte _values
    return item


@contextlib.asynccontextmanager
async def memory_db():
    """Databáze v paměti, která se zavře i při chybě v testu (jinak by vlákno aiosqlite drželo pytest naživu)."""
    db = Database(":memory:")
    await db.open()
    try:
        yield db
    finally:
        await db.close()
