"""/co-jist – náhodné jídlo z dnešních menz a restaurací, když se nemůžeš rozhodnout."""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

from lunch import emoji, service
from lunch.models import Dish, Menu
from utils import render

log = logging.getLogger(__name__)

# rozsah: (emoji, popisek tlačítka)
SCOPES: dict[str, tuple[str, str]] = {
    "vse": ("🌍", "Všude"),
    "menzy": ("🏫", "Menzy"),
    "economy": ("💰", "Jen Economy"),
    "restaurace": ("🍴", "Restaurace"),
}


@dataclass(frozen=True)
class Pick:
    dish: Dish
    menu: Menu
    menza: bool


async def candidates(fetcher, scope: str) -> list[Pick]:
    """Hlavní jídla (bez polévek) z dnešních výpisů; data jdou z cache obnovované na pozadí."""
    picks: list[Pick] = []
    if scope in ("vse", "menzy", "economy"):
        for menu in await service.menza_menus(fetcher, "vse"):
            for d in menu.mains:
                if scope != "economy" or d.economy:
                    picks.append(Pick(d, menu, True))
    if scope in ("vse", "restaurace"):
        for menu in await service.restaurant_menus(fetcher):
            picks += [Pick(d, menu, False) for d in menu.mains]
    return picks


def pick_embed(pick: Pick) -> discord.Embed:
    d, place = pick.dish, pick.menu.place
    name = f"Economy {d.label[1:]}: {d.name}" if d.economy and d.label else d.name
    if d.options:  # pizza dne: vyber rovnou jednu konkrétní
        option, desc = random.choice(d.options)
        name = f"Pizza {option}" + (f" ({desc})" if desc else "")
    embed = discord.Embed(
        title=f"{emoji.for_dish(d)} {name}"[:256],
        url=place.url,
        color=place.color,
    )
    embed.add_field(name="📍 Kde", value=f"{place.emoji} {place.name}", inline=True)
    if d.price:
        embed.add_field(name="💸 Cena", value=d.price + (" (student)" if pick.menza else ""), inline=True)
    if pick.menu.hours:
        embed.add_field(name="🕐 Otevřeno", value=pick.menu.hours, inline=True)
    return embed


async def build_message(bot: commands.Bot, scope: str) -> tuple[str, list[discord.Embed], discord.ui.View]:
    picks = await candidates(bot.fetcher, scope)
    icon, label = SCOPES[scope]
    header = f"### 🎲 Co dneska jíst? – {render.czech_date(service.today())}"
    if not picks:
        content = f"{header}\n_Dnes tu ({label.lower()}) nic není. Asi se nevaří, nebo je zavřeno._ 😢"
        return content, [], build_view(scope)
    pick = random.choice(picks)
    content = f"{header}\n-# Náhodně z {len(picks)} jídel · {icon} {label}"
    return content, [pick_embed(pick)], build_view(scope)


class CojistButton(discord.ui.DynamicItem[discord.ui.Button], template=r"cojist:(?P<scope>[a-z]+):(?P<slot>[rs])"):
    """slot: r = znovu losovat ve stejném rozsahu, s = přepnout rozsah (a losovat)"""

    def __init__(self, scope: str, slot: str, **button_kwargs) -> None:
        super().__init__(discord.ui.Button(custom_id=f"cojist:{scope}:{slot}", **button_kwargs))
        self.scope = scope

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> CojistButton:
        return cls(match["scope"], match["slot"])

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.scope not in SCOPES:
            await interaction.response.send_message("Tohle tlačítko už je zastaralé.", ephemeral=True)
            return
        await interaction.response.defer()
        content, embeds, view = await build_message(interaction.client, self.scope)
        await interaction.edit_original_response(content=content, embeds=embeds, view=view)


def build_view(scope: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(CojistButton(scope, "r", label="Znovu", emoji="🎲", style=discord.ButtonStyle.success, row=0))
    for key, (icon, label) in SCOPES.items():
        current = key == scope
        view.add_item(
            CojistButton(
                key, "s", label=label, emoji=icon, disabled=current,
                style=discord.ButtonStyle.primary if current else discord.ButtonStyle.secondary, row=0,
            )
        )
    return view


class Cojist(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(CojistButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(CojistButton)

    @app_commands.command(name="co-jist", description="🎲 Nevíš, co k obědu? Bot náhodně vybere jídlo z menz a restaurací")
    async def co_jist(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        content, embeds, view = await build_message(self.bot, "vse")
        await interaction.followup.send(content=content, embeds=embeds, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Cojist(bot))
