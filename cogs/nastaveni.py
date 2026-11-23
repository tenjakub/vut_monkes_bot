"""/nastaveni – nastavení bota pro server. Jen pro adminy.

Kdo smí: command má `default_permissions(manage_guild=True)`, takže ho Discord ukáže jen lidem s oprávněním
Spravovat server. Admin serveru může v Nastavení serveru → Integrace → bot → /nastaveni povolit konkrétní roli
(třeba „Admin bota“) a ostatním ho zakázat. Odpověď vidí jen ten, kdo command zadal, takže na tlačítka nikdo
jiný nedosáhne. Command je jen na serveru (v DM s botem není, viz ObedBot.sync_commands).

Zatím: od kolika lidí zakládat událost z /na-pivo (nebo vůbec).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from lunch.service import TZ
from storage import DatabaseUnavailable, settings
from utils.interactions import STALE, reported

log = logging.getLogger(__name__)

UNAVAILABLE = "Databáze teď není dostupná 😵 Nastavení zkus prosím později."
ONLY_GUILD = "Nastavení je jen na serveru."
EVENT_OPTIONS: dict[str, str] = {  # hodnota -> popisek
    "0": "Nezakládat",
    "2": "Od 2 lidí",
    "3": "Od 3 lidí",
    "4": "Od 4 lidí",
    "5": "Od 5 lidí",
}


def _event_text(value: str) -> str:
    label = EVENT_OPTIONS.get(value, value)
    default = " (výchozí)" if value == settings.DEFAULTS[settings.EVENT_MIN_PEOPLE] else ""
    return f"{label.lower()}{default}"


async def message(db, guild_id: int, notice: str = "") -> tuple[str, discord.ui.View]:
    value = settings.get(guild_id, settings.EVENT_MIN_PEOPLE)
    change = await settings.last_change(db, guild_id, settings.EVENT_MIN_PEOPLE)
    lines = [notice] if notice else []
    lines += [
        "### ⚙️ Nastavení bota na tomhle serveru",
        f"📅 **Události z /na-pivo:** {_event_text(value)}",
        "-# Když na pozvánku klikne ✅ Jdu aspoň tolik lidí, bot založí na serveru událost s časem a místem.",
    ]
    if change:
        lines.append(f"-# Naposledy změnil(a) <@{change.updated_by}> {change.updated_at}.")
    lines.append(
        "-# Kdo smí /nastaveni používat, se nastavuje v Nastavení serveru → Integrace → bot → /nastaveni."
    )
    view = discord.ui.View(timeout=None)
    view.add_item(EventSelect(value))
    return "\n".join(lines), view


class EventSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"nastaveni:udalost"):
    def __init__(self, current: str | None = None) -> None:
        options = [
            discord.SelectOption(label=label, value=value, emoji="🚫" if value == "0" else "📅", default=value == current)
            for value, label in EVENT_OPTIONS.items()
        ]
        super().__init__(discord.ui.Select(
            custom_id="nastaveni:udalost", placeholder="📅 Události z /na-pivo", options=options,
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> EventSelect:
        return cls()

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.item.values[0] if self.item.values else None
        if interaction.guild_id is None:
            await interaction.response.send_message(ONLY_GUILD, ephemeral=True)
            return
        if value not in EVENT_OPTIONS:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        db = interaction.client.db
        try:
            await settings.put(db, interaction.guild_id, settings.EVENT_MIN_PEOPLE, value,
                               interaction.user.id, datetime.now(TZ))
            content, view = await message(db, interaction.guild_id, "✅ Uloženo.")
        except DatabaseUnavailable:
            await interaction.response.send_message(UNAVAILABLE, ephemeral=True)
            return
        await interaction.response.edit_message(content=content, view=view)


class Nastaveni(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(EventSelect)
        db = getattr(self.bot, "db", None)
        if db is not None and db.is_open:
            try:
                await settings.load(db)
            except Exception:  # bez uložených nastavení platí výchozí
                log.exception("Načtení nastavení serverů selhalo")

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(EventSelect)

    # extras guild_only: ObedBot.sync_commands ho nedá do DM (bez @guild_only, ať serverová kopie nemá kontext)
    @app_commands.command(name="nastaveni", description="⚙️ Nastavení bota na serveru (jen pro adminy)",
                          extras={"guild_only": True})
    @app_commands.default_permissions(manage_guild=True)
    async def nastaveni(self, interaction: discord.Interaction) -> None:
        if interaction.guild_id is None:
            await interaction.response.send_message(ONLY_GUILD, ephemeral=True)
            return
        try:
            content, view = await message(self.bot.db, interaction.guild_id)
        except DatabaseUnavailable:
            await interaction.response.send_message(UNAVAILABLE, ephemeral=True)
            return
        await interaction.response.send_message(content, view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Nastaveni(bot))
