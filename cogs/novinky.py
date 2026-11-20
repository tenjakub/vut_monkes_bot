"""/novinky – co je nového v posledních verzích bota (z CHANGELOG.md), s listováním."""

from __future__ import annotations

import re

import discord
from discord import app_commands
from discord.ext import commands

from utils import changelog, render

PER_PAGE = 3
COLOR_NEWEST = 0x2F9E44
COLOR_OLDER = 0x868E96


def _release_embed(release: changelog.Release, newest: bool) -> discord.Embed:
    title = f"🆕 Verze {release.version}" if newest else f"Verze {release.version}"
    if release.title:
        title += f" – {release.title}"
    body = release.body or "_bez popisu_"
    if len(body) > 4000:
        body = body[:4000].rsplit("\n", 1)[0] + "\n…"
    embed = discord.Embed(
        title=title,
        # Discord slučuje embedy se stejnou URL, proto verze v odkazu
        url=f"{changelog.URL}?verze={release.version}",
        description=body,
        color=COLOR_NEWEST if newest else COLOR_OLDER,
    )
    embed.set_footer(text=f"vydáno {render.czech_date(release.date)} {release.date.year}")
    return embed


def build_message(page: int = 0) -> tuple[str, list[discord.Embed], discord.ui.View]:
    releases = changelog.load()
    pages = max(1, -(-len(releases) // PER_PAGE))
    page = min(max(page, 0), pages - 1)
    shown = releases[page * PER_PAGE : (page + 1) * PER_PAGE]
    embeds = [_release_embed(r, newest=(page == 0 and i == 0)) for i, r in enumerate(shown)]

    current = changelog.current_version()
    content = "### 🆕 Novinky ve VUT Monkes botovi"
    if current:
        content += f"\nTeď běží **verze {current}**."
    if pages > 1:
        content += f" · strana {page + 1}/{pages}"
    if not releases:
        content += "\n_Changelog je zatím prázdný._"
    return content, embeds, build_view(page, pages)


class NovinkyButton(discord.ui.DynamicItem[discord.ui.Button], template=r"novinky:(?P<page>\d+):(?P<slot>[pn])"):
    """Listování po stránkách. slot: p = novější, n = starší (kvůli unikátnímu custom_id)."""

    def __init__(self, page: int, slot: str, **button_kwargs) -> None:
        super().__init__(discord.ui.Button(custom_id=f"novinky:{page}:{slot}", **button_kwargs))
        self.page = page

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> NovinkyButton:
        return cls(int(match["page"]), match["slot"])

    async def callback(self, interaction: discord.Interaction) -> None:
        content, embeds, view = build_message(self.page)
        await interaction.response.edit_message(content=content, embeds=embeds, view=view)


def build_view(page: int, pages: int) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    if pages > 1:
        view.add_item(
            NovinkyButton(max(page - 1, 0), "p", label="Novější", emoji="◀️", disabled=page == 0,
                          style=discord.ButtonStyle.secondary)
        )
        view.add_item(
            NovinkyButton(min(page + 1, pages - 1), "n", label="Starší", emoji="▶️", disabled=page >= pages - 1,
                          style=discord.ButtonStyle.secondary)
        )
    view.add_item(discord.ui.Button(label="Celý changelog", url=changelog.URL))
    return view


class Novinky(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(NovinkyButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(NovinkyButton)

    @app_commands.command(name="novinky", description="🆕 Co je nového v posledních verzích bota")
    async def novinky(self, interaction: discord.Interaction) -> None:
        content, embeds, view = build_message(0)
        await interaction.response.send_message(content=content, embeds=embeds, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Novinky(bot))
