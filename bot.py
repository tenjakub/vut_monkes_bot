"""Vstupní bod bota: `python bot.py`"""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from lunch.fetcher import Fetcher

log = logging.getLogger("bot")

EXTENSIONS = ["cogs.menza", "cogs.restaurace", "cogs.mhd"]


class ObedBot(commands.Bot):
    def __init__(self) -> None:
        # Slash commandy nepotřebují žádné privilegované intenty
        super().__init__(command_prefix=commands.when_mentioned, intents=discord.Intents.default())
        self.fetcher = Fetcher()

    async def setup_hook(self) -> None:
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        self.tree.on_error = self.on_app_command_error

        if config.GUILD_IDS:
            # synchronizace do konkrétního serveru je okamžitá (globální trvá až hodinu)
            for gid in config.GUILD_IDS:
                guild = discord.Object(id=gid)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info("Synchronizováno %d commandů na server %s", len(synced), gid)
        else:
            synced = await self.tree.sync()
            log.info("Synchronizováno %d globálních commandů", len(synced))

    async def on_ready(self) -> None:
        log.info("Přihlášen jako %s (%s)", self.user, self.user.id if self.user else "?")

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        log.exception("Chyba v commandu", exc_info=error)
        msg = "Něco se pokazilo 😵 Zkus to prosím za chvíli znovu."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    async def close(self) -> None:
        await self.fetcher.close()
        await super().close()


def main() -> None:
    discord.utils.setup_logging(level=logging.INFO)
    ObedBot().run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
