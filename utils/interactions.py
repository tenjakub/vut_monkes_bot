"""Společné věci pro tlačítka a výběry: chybové hlášky a stav hlasovacích zpráv (/obed, /na-pivo).

- `@reported` na `callback` tlačítka: když callback spadne, uživatel dostane hlášku (jen pro sebe) jako
  u slash commandů. Bez toho discord.py chybu jen zaloguje a tlačítko „nic neudělá“.
- `MessageState`: zámek na zprávu (dvě kliknutí naráz) a poslední embed, který do ní bot zapsal.
  `interaction.message` je totiž snímek zprávy z okamžiku kliknutí, takže druhé z dvou rychlých kliknutí
  by bez toho přepsalo to první. Obojí je omezené na posledních pár set zpráv, ať paměť neroste.
"""

from __future__ import annotations

import asyncio
import functools
import logging
from collections import OrderedDict
from collections.abc import Awaitable, Callable

import discord

log = logging.getLogger("bot.interactions")

STALE = "Tohle tlačítko už je zastaralé."


def error_text() -> str:
    import config  # až tady: config bez DISCORD_TOKEN ukončí program (testy ho nemají)

    return (
        "Něco se pokazilo 😵 Zkus to prosím za chvíli znovu.\n"
        f"-# Když to nepřestane, nahlas to prosím na {config.ISSUES_URL} (verze {config.BOT_VERSION})"
    )


async def send_error(interaction: discord.Interaction) -> None:
    """Chybová hláška jen pro toho, kdo klikl / zadal command."""
    try:
        if interaction.response.is_done():
            await interaction.followup.send(error_text(), ephemeral=True)
        else:
            await interaction.response.send_message(error_text(), ephemeral=True)
    except discord.HTTPException:
        log.exception("Ani chybovou hlášku se nepodařilo poslat")


def reported(callback: Callable[..., Awaitable[None]]):
    """Dekorátor pro `callback(self, interaction)` tlačítek, výběrů a `on_submit` oken."""

    @functools.wraps(callback)
    async def wrapper(self, interaction: discord.Interaction, *args, **kwargs) -> None:
        try:
            await callback(self, interaction, *args, **kwargs)
        except Exception:
            log.exception("Chyba v %s", type(self).__name__)
            await send_error(interaction)

    return wrapper


class MessageState:
    """Zámky a poslední zapsané embedy hlasovacích zpráv (podle ID zprávy)."""

    def __init__(self, size: int = 200) -> None:
        self.size = size
        self._locks: OrderedDict[int, asyncio.Lock] = OrderedDict()
        self._embeds: OrderedDict[int, discord.Embed] = OrderedDict()

    def _touch(self, store: OrderedDict, key: int, value) -> None:
        store[key] = value
        store.move_to_end(key)
        while len(store) > self.size:
            store.popitem(last=False)

    def lock(self, message_id: int) -> asyncio.Lock:
        lock = self._locks.get(message_id) or asyncio.Lock()
        self._touch(self._locks, message_id, lock)
        return lock

    def embed(self, message: discord.Message | None) -> discord.Embed | None:
        """Embed, který bot do zprávy zapsal naposledy, jinak první embed zprávy."""
        if message is None:
            return None
        return self._embeds.get(message.id) or (message.embeds[0] if message.embeds else None)

    def remember(self, message_id: int, embed: discord.Embed) -> None:
        self._touch(self._embeds, message_id, embed)
