"""/statistiky – které commandy se používají nejvíc. Testovací využití databáze (storage/usage.py).

Počítá se každé úspěšné použití slash commandu (`on_app_command_completion`), jen počty po dnech, ne kdo.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from lunch.service import today
from storage import Database, DatabaseUnavailable
from storage import usage
from utils import render
from utils.interactions import STALE, reported

log = logging.getLogger(__name__)

COLOR = 0x7048E8
# období: klíč v custom_id -> (popisek tlačítka, počet dní nebo None = od začátku)
PERIODS: dict[str, tuple[str, int | None]] = {
    "7": ("7 dní", 7),
    "30": ("30 dní", 30),
    "vse": ("Od začátku", None),
}
DEFAULT_PERIOD = "30"
BAR = 8  # délka „sloupečku“ u nejpoužívanějšího commandu
UNAVAILABLE = "Databáze teď není dostupná 😵 Statistiky se ukážou, až zase poběží."


def _bar(count: int, best: int) -> str:
    full = max(1, round(BAR * count / best)) if best else 0
    return "▰" * full + "▱" * (BAR - full)


def _times(n: int) -> str:
    return f"{n}×"


async def build_message(db: Database, period: str) -> tuple[str, list[discord.Embed], discord.ui.View]:
    label, days = PERIODS[period]
    since = today() - timedelta(days=days - 1) if days else None
    rows = await usage.top(db, since)
    first = await usage.first_day(db)

    total = sum(r.count for r in rows)
    info = [f"za posledních {label}" if days else "od začátku", f"celkem **{_times(total)}**"]
    if first:
        info.append(f"sbírá se od {first.day}. {first.month}. {first.year}")
    content = "### 📊 Které commandy používáme\n-# " + " · ".join(info)

    embed = discord.Embed(color=COLOR)
    if rows:
        best = rows[0].count
        fields = [render.Field(f"/{r.command}", f"**{_times(r.count)}**\n`{_bar(r.count, best)}`") for r in rows]
        render.add_fields(embed, fields, 4000)
    else:
        embed.description = "_Zatím se nic nepočítá._ 🦗"
    embed.set_footer(text="Počítá se jen kolikrát se který command použil, ne kdo ho použil.")
    return content, [embed], build_view(period)


class StatistikyButton(discord.ui.DynamicItem[discord.ui.Button], template=r"statistiky:(?P<period>[a-z0-9]+)"):
    def __init__(self, period: str, **button_kwargs) -> None:
        super().__init__(discord.ui.Button(custom_id=f"statistiky:{period}", **button_kwargs))
        self.period = period

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> StatistikyButton:
        return cls(match["period"])

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        if self.period not in PERIODS:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        try:
            content, embeds, view = await build_message(interaction.client.db, self.period)
        except DatabaseUnavailable:
            await interaction.response.send_message(UNAVAILABLE, ephemeral=True)
            return
        await interaction.response.edit_message(content=content, embeds=embeds, view=view)


def build_view(period: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for key, (label, _) in PERIODS.items():
        current = key == period
        view.add_item(StatistikyButton(key, label=label, disabled=current,
                                       style=discord.ButtonStyle.primary if current else discord.ButtonStyle.secondary))
    return view


class Statistiky(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(StatistikyButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(StatistikyButton)

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: discord.Interaction, command) -> None:
        """Každé úspěšné použití slash commandu +1. Bez databáze se prostě nepočítá."""
        db: Database | None = getattr(self.bot, "db", None)
        if db is None or not db.is_open:
            return
        try:
            await usage.record(db, command.qualified_name, today())
        except Exception:
            log.exception("Zápis statistiky commandu selhal")

    @app_commands.command(name="statistiky", description="📊 Které commandy bota se používají nejvíc")
    async def statistiky(self, interaction: discord.Interaction) -> None:
        try:
            content, embeds, view = await build_message(self.bot.db, DEFAULT_PERIOD)
        except DatabaseUnavailable:
            await interaction.response.send_message(UNAVAILABLE, ephemeral=True)
            return
        await interaction.response.send_message(content=content, embeds=embeds, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Statistiky(bot))
