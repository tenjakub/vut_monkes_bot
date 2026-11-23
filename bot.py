"""Vstupní bod bota: `python bot.py`"""

from __future__ import annotations

import asyncio
import logging
import signal
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

import config
from lunch.fetcher import Fetcher
from lunch.service import today
from storage import Database
from utils import changelog
from utils.interactions import send_error
from utils.loading import LoadingTracker

log = logging.getLogger("bot")

EXTENSIONS = ["cogs.hodnoceni", "cogs.menza", "cogs.restaurace", "cogs.mhd", "cogs.kola", "cogs.slevy", "cogs.hlidat", "cogs.cojist", "cogs.obed", "cogs.napivo", "cogs.cenapiva", "cogs.pocasi", "cogs.otevreno", "cogs.statistiky", "cogs.koleje", "cogs.novinky"]


LOADING_SUFFIX = " · ⏳"


def status_text(loading: bool = False) -> str:
    """Status pod jménem bota: verze z CHANGELOG.md + commit, např. "verze 1.1 · 3227e1b".
    Během delšího načítání dat na pozadí s ⏳ na konci."""
    release = changelog.current_version()
    text = f"verze {release} · {config.BOT_VERSION}" if release else f"verze {config.BOT_VERSION}"
    return text + (LOADING_SUFFIX if loading else "")


class ObedBot(commands.Bot):
    def __init__(self) -> None:
        # Slash commandy nepotřebují žádné privilegované intenty
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
            # vlastní status pod jménem bota – verze, ať je hned vidět, co běží
            # (po startu se hned načítají data, proto rovnou s ⏳; on_ready ho upraví podle skutečnosti)
            activity=discord.CustomActivity(name=status_text(loading=config.BACKGROUND_REFRESH)),
        )
        self.fetcher = Fetcher()
        self.db = Database(config.DB_PATH)
        self.background_refresh = config.BACKGROUND_REFRESH  # obnova dat na pozadí (v testech vypnutá)
        self.loading = LoadingTracker(self.update_presence)  # log "načteno" a ⏳ ve statusu

    async def update_presence(self) -> None:
        """Status podle toho, jestli se zrovna (déle) načítají data."""
        if self.is_ready():
            await self.change_presence(activity=discord.CustomActivity(name=status_text(self.loading.showing)))

    async def setup_hook(self) -> None:
        log.info("Startuje VUT Monkes bot, %s", status_text())
        self._handle_sigterm()
        self.heartbeat.start()
        try:
            await self.db.open()
        except Exception:  # bez databáze běží všechno ostatní, jen funkce s databází hlásí, že nejde
            log.exception("Databázi %s se nepodařilo otevřít", config.DB_PATH)
        if self.db.is_open and self.background_refresh:
            self.backup.start()
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        self.loading.seal()  # všechny zdroje se zaregistrovaly -> souhrn "vše načteno" může přijít
        self.tree.on_error = self.on_app_command_error

        await self.sync_commands()

    async def sync_commands(self) -> None:
        """Registrace slash commandů na serverech a v soukromém chatu (DM) s botem.

        S GUILD_IDS:
          1. Na vybraných serverech jako serverové commandy (objeví se hned). Kontext se
             neposílá, takže na serveru se chovají stejně jako dřív.
          2. Globálně, ale jen pro DM s botem. Na serverech se tak globální sada neukazuje
             a commandy tam nejsou dvakrát.
          Pozor: discord.py posílá u serverové kopie i globálního commandu stejný objekt,
          proto se kontext DM nastaví na stromu až PO synchronizaci serverů.
        Bez GUILD_IDS: jedna globální sada pro servery i DM.
        """
        tree = self.tree
        installs = app_commands.AppInstallationType(guild=True, user=False)
        if config.GUILD_IDS:
            guilds = [discord.Object(id=gid) for gid in config.GUILD_IDS]
            for guild in guilds:
                tree.copy_global_to(guild=guild)
                synced = await tree.sync(guild=guild)
                log.info("Synchronizováno %d commandů na server %s", len(synced), guild.id)
            tree.allowed_contexts = app_commands.AppCommandContext(guild=False, dm_channel=True, private_channel=False)
            tree.allowed_installs = installs
            synced = await tree.sync()
            log.info("Synchronizováno %d commandů pro DM s botem", len(synced))
        else:
            tree.allowed_contexts = app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=False)
            tree.allowed_installs = installs
            synced = await tree.sync()
            log.info("Synchronizováno %d globálních commandů (servery + DM)", len(synced))

    def _handle_sigterm(self) -> None:
        """`docker stop` (a Watchtower při aktualizaci) posílá SIGTERM: bot se pak ukončí slušně,
        zavře databázi i spojení. Bez toho by ho Python ukončil okamžitě."""
        def stop() -> None:
            self._stopping = asyncio.create_task(self.close())  # reference, ať task nesežere garbage collector

        try:
            asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, stop)
        except (NotImplementedError, RuntimeError):  # Windows
            pass

    @tasks.loop(hours=24)
    async def backup(self) -> None:
        """Denní záloha databáze do data/backups (posledních 7 dní). Po startu hned, pokud dnešní chybí."""
        try:
            path = await self.db.backup(Path(config.DB_PATH).parent / "backups", today())
            if path:
                log.info("🗄️ Záloha databáze: %s", path)
        except Exception:
            log.exception("Záloha databáze selhala")

    @tasks.loop(seconds=30)
    async def heartbeat(self) -> None:
        """Pro Docker healthcheck: soubor se obnovuje, jen když je bot připojený k Discordu."""
        if self.is_ready() and not self.is_closed():
            Path(config.HEALTH_FILE).touch()

    async def on_ready(self) -> None:
        log.info("Přihlášen jako %s (%s)", self.user, self.user.id if self.user else "?")
        # status podle skutečnosti: ⏳ jen pokud se ještě něco načítá (on_ready přijde i po výpadku spojení)
        self.loading.showing = bool(self.loading.active)
        await self.update_presence()

    async def on_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        log.exception("Chyba v commandu", exc_info=error)
        await send_error(interaction)

    async def close(self) -> None:
        self.heartbeat.cancel()
        self.backup.cancel()
        await self.fetcher.close()
        await self.db.close()
        await super().close()


def main() -> None:
    discord.utils.setup_logging(level=logging.INFO)
    ObedBot().run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
    main()
