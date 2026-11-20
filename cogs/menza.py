"""/ppv, /purkyne, /menzy – Economy (případně všechna) jídla z menz VUT."""

from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands

from lunch import kam, service
from lunch.models import Menu
from utils import render

MODE_ECO = "eco"
MODE_ALL = "all"

VSE_DESCRIPTION = "Ukázat i polévky a ostatní hlavní jídla, ne jen Economy (saláty a přílohy se vynechávají)"

# krátké popisky na tlačítka (limit 80 znaků, ale chceme to čitelné)
GROUP_BUTTONS = {
    "ppv": "Kolejní · Mozzarella · SP",
    "purkyne": "Purkyňova · SP",
    "vse": "Všechny menzy",
}


def menza_fields(menu: Menu, mode: str) -> list[render.Field]:
    economy = [render.dish_field(d) for d in menu.economy]
    if mode == MODE_ECO:
        return economy
    # "vše" = polévky + hlavní jídla, bez salátů/příloh/dezertů.
    # Economy mají štítek E1, E2…, ostatní jídla jen cenu.
    others = [render.dish_field(d) for d in menu.mains if not d.economy]
    return render.soup_field(menu.soups) + economy + others


async def build_message(
    bot: commands.Bot, group: str, mode: str, force: bool = False
) -> tuple[str, list[discord.Embed], discord.ui.View]:
    menus = await service.menza_menus(bot.fetcher, group, force=force)
    limit = render.per_embed_limit(len(menus))
    empty = "Dnes tu není žádné Economy jídlo." if mode == MODE_ECO else "Dnes tu nejsou žádná hlavní jídla."
    embeds = [render.menu_embed(m, menza_fields(m, mode), limit, empty) for m in menus]
    title = "Economy menu" if mode == MODE_ECO else "Jídla v menzách"
    content = render.header(f"🍽️ {title}", menus, f"💰 ceny: {kam.PRICE_LABEL}")
    return content, embeds, build_view(group, mode)


class MenzaButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"menza:(?P<group>[a-z]+):(?P<mode>eco|all):(?P<slot>[gmr])",
):
    """Tlačítko pod výpisem. Stav je zakódovaný v custom_id, takže funguje i po restartu bota.

    slot: g = přepnutí skupiny menz, m = přepnutí režimu, r = obnovit
    """

    def __init__(self, group: str, mode: str, slot: str, **button_kwargs) -> None:
        super().__init__(discord.ui.Button(custom_id=f"menza:{group}:{mode}:{slot}", **button_kwargs))
        self.group = group
        self.mode = mode
        self.slot = slot

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> MenzaButton:
        return cls(match["group"], match["mode"], match["slot"])

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.group not in kam.GROUPS:
            await interaction.response.send_message("Tohle tlačítko už je zastaralé.", ephemeral=True)
            return
        await interaction.response.defer()
        content, embeds, view = await build_message(
            interaction.client, self.group, self.mode, force=self.slot == "r"
        )
        await interaction.edit_original_response(content=content, embeds=embeds, view=view)


def build_view(group: str, mode: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for key, label in GROUP_BUTTONS.items():
        current = key == group
        view.add_item(
            MenzaButton(
                key,
                mode,
                "g",
                label=label,
                style=discord.ButtonStyle.primary if current else discord.ButtonStyle.secondary,
                disabled=current,
                row=0,
            )
        )
    for key, label, emoji in ((MODE_ECO, "Jen Economy", "💰"), (MODE_ALL, "Všechna jídla", "📋")):
        current = key == mode
        view.add_item(
            MenzaButton(
                group,
                key,
                "m",
                label=label,
                emoji=emoji,
                style=discord.ButtonStyle.success if current else discord.ButtonStyle.secondary,
                disabled=current,
                row=1,
            )
        )
    view.add_item(MenzaButton(group, mode, "r", label="Obnovit", emoji="🔄", style=discord.ButtonStyle.secondary, row=1))
    view.add_item(discord.ui.Button(label="Web KaM", url=kam.OVERVIEW_URL, row=1))
    return view


class Menza(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(MenzaButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(MenzaButton)

    async def _send(self, interaction: discord.Interaction, group: str, vse: bool) -> None:
        await interaction.response.defer(thinking=True)
        content, embeds, view = await build_message(self.bot, group, MODE_ALL if vse else MODE_ECO)
        await interaction.followup.send(content=content, embeds=embeds, view=view)

    # Každá skupina menz má vlastní command, takže stačí napsat /ppv + Enter.
    # Mezi skupinami se pak dá přepínat i tlačítky pod zprávou.

    @app_commands.command(name="ppv", description="🍽️ Economy obědy v menzách Kolejní, Mozzarella a Starý pivovar")
    @app_commands.describe(vse=VSE_DESCRIPTION)
    async def ppv(self, interaction: discord.Interaction, vse: bool = False) -> None:
        await self._send(interaction, "ppv", vse)

    @app_commands.command(name="purkyne", description="🍽️ Economy obědy v menzách Purkyňova a Starý pivovar")
    @app_commands.describe(vse=VSE_DESCRIPTION)
    async def purkyne(self, interaction: discord.Interaction, vse: bool = False) -> None:
        await self._send(interaction, "purkyne", vse)

    @app_commands.command(name="menzy", description="🍽️ Economy obědy ve všech menzách VUT, kde je vaří")
    @app_commands.describe(vse=VSE_DESCRIPTION)
    async def menzy(self, interaction: discord.Interaction, vse: bool = False) -> None:
        await self._send(interaction, "vse", vse)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Menza(bot))
