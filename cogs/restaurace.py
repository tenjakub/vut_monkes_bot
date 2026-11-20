"""/restaurace – polední menu vybraných restaurací."""

from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from lunch import service
from lunch.models import Menu
from utils import render


log = logging.getLogger(__name__)


def restaurant_fields(menu: Menu) -> list[render.Field]:
    # stejná mřížka kartiček jako u menz, polévka přes celou šířku nahoře,
    # jídla s výběrem (pizza dne v La Stradě) přes celou šířku pod mřížkou, i s popisem každé možnosti
    simple = [render.dish_field(d) for d in menu.mains if not d.options]
    with_options = [render.options_field(d) for d in menu.mains if d.options]
    return render.soup_field(menu.soups) + simple + with_options


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
                row=1,
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
        if getattr(self.bot, "background_refresh", True):
            self.prefetch.start()

    async def cog_unload(self) -> None:
        self.prefetch.cancel()
        self.bot.remove_dynamic_items(RefreshButton)

    @tasks.loop(minutes=service.RESTAURANT_REFRESH_MINUTES)
    async def prefetch(self) -> None:
        """Přes den stahuje polední menu restaurací na pozadí, ať /restaurace odpovídá hned."""
        if not service.is_lunch_time():
            return
        try:
            await service.restaurant_menus(self.bot.fetcher, force=True)
        except Exception:
            log.exception("Obnova menu restaurací selhala")

    @app_commands.command(
        name="restaurace",
        description="Polední menu restaurací (U 3 opic, Padagali, La Strada, U Karla, Portoriko)",
    )
    async def restaurace(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        content, embeds, view = await build_message(self.bot)
        await interaction.followup.send(content=content, embeds=embeds, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Restaurace(bot))
