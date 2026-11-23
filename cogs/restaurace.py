"""/restaurace – polední menu vybraných restaurací."""

from __future__ import annotations

import logging
import re

import discord
from discord import app_commands
from discord.ext import commands, tasks

from lunch import service
from lunch.models import NO_MENU, Menu
from cogs import hodnoceni
from cogs.obed import ObedNewButton
from storage import menus as stored_menus
from utils import loading, render
from utils.interactions import reported


log = logging.getLogger(__name__)


def restaurant_fields(menu: Menu, notes: dict[str, str] | None = None) -> list[render.Field]:
    # stejná mřížka kartiček jako u menz, polévka přes celou šířku nahoře,
    # jídla s výběrem (pizza dne v La Stradě) a skupiny (pizzy a těstoviny v Sesamu) přes celou šířku
    # pod mřížkou, i s popisem nebo přísadami
    notes = notes or {}
    simple = [render.dish_field(d, note=notes.get(d.name)) for d in menu.mains if not d.options and not d.group]
    with_options = [render.options_field(d) for d in menu.mains if d.options]
    groups: dict[str, list] = {}
    for d in menu.mains:
        if d.group and not d.options:
            groups.setdefault(d.group, []).append(d)
    grouped = [render.group_field(g, dishes) for g, dishes in groups.items()]
    return render.soup_field(menu.soups) + simple + with_options + grouped


async def build_message(
    bot: commands.Bot, force: bool = False
) -> tuple[str, list[discord.Embed], discord.ui.View]:
    menus = await service.restaurant_menus(bot.fetcher, force=force)
    limit = render.per_embed_limit(len(menus))
    notes = await hodnoceni.rating_notes(bot, menus)
    embeds = [render.menu_embed(m, restaurant_fields(m, notes.get(m.place.key)), limit, NO_MENU) for m in menus]
    content = render.header("🍴 Polední menu restaurací", menus)
    return content, embeds, build_view()


class RefreshButton(discord.ui.DynamicItem[discord.ui.Button], template=r"restaurace:refresh"):
    def __init__(self, row: int | None = None) -> None:
        super().__init__(
            discord.ui.Button(
                custom_id="restaurace:refresh",
                label="Obnovit",
                emoji="🔄",
                style=discord.ButtonStyle.secondary,
                row=row,
            )
        )

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> RefreshButton:
        return cls()

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        content, embeds, view = await build_message(interaction.client, force=True)
        await interaction.edit_original_response(content=content, embeds=embeds, view=view)


def build_view() -> discord.ui.View:
    """Nahoře odkazy na weby restaurací (po pěti v řadě), pod nimi Obnovit a Svolat oběd."""
    view = discord.ui.View(timeout=None)
    for i, r in enumerate(service.RESTAURANTS):
        view.add_item(discord.ui.Button(label=r.place.name, emoji=r.place.emoji, url=r.place.url, row=i // 5))
    actions = (len(service.RESTAURANTS) + 4) // 5  # první řada pod odkazy
    view.add_item(RefreshButton(row=actions))
    view.add_item(hodnoceni.RateButton(hodnoceni.RESTAURANTS, row=actions))  # ⭐ ohodnotit dnešní jídlo
    view.add_item(ObedNewButton(row=actions))  # rovnou svolat, kdo jde na oběd
    return view


class Restaurace(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(RefreshButton)
        if getattr(self.bot, "background_refresh", True):
            self.prefetch.start()
            loading.expect(self.bot, "menu restaurací")

    async def cog_unload(self) -> None:
        self.prefetch.cancel()
        self.bot.remove_dynamic_items(RefreshButton)

    @tasks.loop(minutes=service.RESTAURANT_REFRESH_MINUTES)
    async def prefetch(self) -> None:
        """Přes den stahuje polední menu restaurací na pozadí, ať /restaurace odpovídá hned.
        Mimo obědy se jen dotáhne, co v cache z dneška chybí (třeba po restartu bota večer)."""
        try:
            async with loading.track(self.bot, "menu restaurací"):
                menus = await service.restaurant_menus(self.bot.fetcher, force=service.is_lunch_time())
            await stored_menus.remember(getattr(self.bot, "db", None), menus)  # historie pro statistiky
        except Exception:
            log.exception("Obnova menu restaurací selhala")

    @app_commands.command(
        name="restaurace",
        description="Polední menu restaurací (U 3 opic, Padagali, La Strada, U Karla, Portoriko, Sesamo)",
    )
    async def restaurace(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        content, embeds, view = await build_message(self.bot)
        await interaction.followup.send(content=content, embeds=embeds, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Restaurace(bot))
