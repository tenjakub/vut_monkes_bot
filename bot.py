"""Vstupní bod bota: `python bot.py`"""

from __future__ import annotations

import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from lunch.fetcher import Fetcher

log = logging.getLogger("bot")

EXTENSIONS = ["cogs.menza", "cogs.restaurace", "cogs.mhd"]


def status_text() -> str:
    return f"🍽️ /ppv · 🚏 /mhd · verze {config.BOT_VERSION}"


class ObedBot(commands.Bot):
    def __init__(self) -> None:
        # Slash commandy nepotřebují žádné privilegované intenty
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
            # vlastní status pod jménem bota – verze, ať je hned vidět, co běží
            activity=discord.CustomActivity(name=status_text()),
        )
        self.fetcher = Fetcher()

    async def setup_hook(self) -> None:
        log.info("Startuje VUT Monkes bot, verze %s", config.BOT_VERSION)
        self.heartbeat.start()
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        self.tree.on_error = self.on_app_command_error

        if config.GUILD_IDS:
            # Synchronizace do konkrétních serverů je okamžitá (globální trvá až hodinu).
            guilds = [discord.Object(id=gid) for gid in config.GUILD_IDS]
            for guild in guilds:
                self.tree.copy_global_to(guild=guild)
            # Globální commandy z dřívějška (třeba z běhu bez GUILD_IDS) smazat,
            # jinak by se na serveru ukazovaly dvakrát (globální + serverová kopie).
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            for guild in guilds:
                synced = await self.tree.sync(guild=guild)
                log.info("Synchronizováno %d commandů na server %s", len(synced), guild.id)
        else:
            synced = await self.tree.sync()
            log.info("Synchronizováno %d globálních commandů", len(synced))

    @tasks.loop(seconds=30)
    async def heartbeat(self) -> None:
        """Pro Docker healthcheck: soubor se obnovuje, jen když je bot připojený k Discordu."""
        if self.is_ready() and not self.is_closed():
            Path(config.HEALTH_FILE).touch()

    async def on_ready(self) -> None:
        log.info("Přihlášen jako %s (%s)", self.user, self.user.id if self.user else "?")

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        log.exception("Chyba v commandu", exc_info=error)
        msg = (
            "Něco se pokazilo 😵 Zkus to prosím za chvíli znovu.\n"
            f"-# Když to nepřestane, nahlas to prosím na {config.ISSUES_URL} (verze {config.BOT_VERSION})"
        )
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    async def close(self) -> None:
        self.heartbeat.cancel()
        await self.fetcher.close()
        await super().close()


def main() -> None:
    discord.utils.setup_logging(level=logging.INFO)
    ObedBot().run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
