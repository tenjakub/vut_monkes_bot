"""/koleje – na kterých kolejích bydlím. Podle toho /mhd a /kola rovnou ukážou správné koleje.

Nerozhodnuto (výchozí) = všechno jako dřív. Jiným lidem se nic nemění, tlačítka pod zprávami fungují stejně.
"""

from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands

from storage import DatabaseUnavailable, prefs
from utils.interactions import STALE, reported

UNAVAILABLE = "Databáze teď není dostupná 😵 Koleje si nastav prosím později."
UNDECIDED = "nic"
CHOICES: dict[str, tuple[str, str]] = {  # klíč v custom_id -> (emoji, popisek)
    "ppv": ("🏘️", "PPV"),
    "purkyne": ("🏢", "Purkyně"),
    UNDECIDED: ("🤷", "Nerozhodnuto"),
}


def message(current: str | None, notice: str = "") -> tuple[str, discord.ui.View]:
    lines = [notice] if notice else []
    icon, label = CHOICES[current or UNDECIDED]
    lines += [
        "### 🏠 Moje koleje",
        f"Teď: {icon} **{label}**",
        "-# `/mhd` a `/kola` ti rovnou ukážou tvoje koleje (přepnout jde dál tlačítky). "
        "Když je nerozhodnuto, chovají se jako dřív. Ostatním se nic nemění.",
    ]
    view = discord.ui.View(timeout=None)
    for key, (emoji, text) in CHOICES.items():
        chosen = key == (current or UNDECIDED)
        view.add_item(DormButton(key, label=text, emoji=emoji, disabled=chosen,
                                 style=discord.ButtonStyle.primary if chosen else discord.ButtonStyle.secondary))
    return "\n".join(lines), view


class DormButton(discord.ui.DynamicItem[discord.ui.Button], template=r"koleje:(?P<dorm>[a-z]+)"):
    def __init__(self, dorm: str, **button_kwargs) -> None:
        super().__init__(discord.ui.Button(custom_id=f"koleje:{dorm}", **button_kwargs))
        self.dorm = dorm

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> DormButton:
        return cls(match["dorm"])

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        if self.dorm not in CHOICES:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        value = None if self.dorm == UNDECIDED else self.dorm
        try:
            await prefs.put(interaction.client.db, interaction.user.id, prefs.DORM, value)
        except DatabaseUnavailable:
            await interaction.response.send_message(UNAVAILABLE, ephemeral=True)
            return
        content, view = message(value, "✅ Uloženo.")
        await interaction.response.edit_message(content=content, view=view)


class Koleje(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(DormButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(DormButton)

    @app_commands.command(name="koleje", description="🏠 Na kterých kolejích bydlíš – /mhd a /kola pak ukážou rovnou ty tvoje")
    async def koleje(self, interaction: discord.Interaction) -> None:
        db = self.bot.db
        if not db.is_open:
            await interaction.response.send_message(UNAVAILABLE, ephemeral=True)
            return
        content, view = message(await prefs.dorm(db, interaction.user.id))
        await interaction.response.send_message(content, view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Koleje(bot))
