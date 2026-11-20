"""/restaurace – polední menu vybraných restaurací."""

from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands

from lunch import service
from lunch.models import Menu
from utils import render


def restaurant_fields(menu: Menu) -> list[render.Field]:
    # Názvy jídel v restauracích jsou dlouhé, takže tady jedno jídlo na řádek místo mřížky
    return render.soup_field(menu.soups) + [render.dish_field(d, inline=False) for d in menu.mains]


async def build_message(
    bot: commands.Bot, force: bool = False
) -> tuple[str, list[discord.Embed], discord.ui.View]:
    menus = await service.restaurant_menus(bot.fetcher, force=force)
    limit = render.per_embed_limit(len(menus))
    embeds = [render.menu_embed(m, restaurant_fields(m), limit, "Menu je prázdné.") for m in menus]
    content = render.header("🍴 Polední menu restaurací", menus)
    return content, embeds, build_view()


class RefreshButton(discord.ui.DynamicItem[discord.ui.Button], template=r"restaurace:refresh"):
    def __init__(self) -> None:
        super().__init__(
            discord.ui.Button(
                custom_id="restaurace:refresh",
                label="Obnovit",
                emoji="🔄",
                style=discord.ButtonStyle.secondary,
                row=0,
            )
        )

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> RefreshButton:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        content, embeds, view = await build_message(interaction.client, force=True)
        await interaction.edit_original_response(content=content, embeds=embeds, view=view)


def build_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(RefreshButton())
    for r in service.RESTAURANTS:
        view.add_item(discord.ui.Button(label=r.place.name, emoji=r.place.emoji, url=r.place.url, row=0))
    return view


class Restaurace(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(RefreshButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(RefreshButton)

    @app_commands.command(
        name="restaurace",
        description="Polední menu restaurací (U 3 opic, Padagali, La Strada)",
    )
    async def restaurace(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        content, embeds, view = await build_message(self.bot)
        await interaction.followup.send(content=content, embeds=embeds, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Restaurace(bot))
