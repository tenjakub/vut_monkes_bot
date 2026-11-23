"""⭐ Hodnocení jídel pod výpisy menz a restaurací: 👍 dobré / 😐 neurazí / 👎 špatné.

Postup (všechno vidí jen ten, kdo hodnotí, takže to nikoho neruší):
1. ⭐ Ohodnotit pod /ppv, /purkyne, /menzy nebo /restaurace → výběr dnešního jídla,
2. tři tlačítka 👍 😐 👎 → uloženo, s tlačítkem ↩️ Zrušit (kdyby se člověk překlikl).

Výběr jídla je zároveň „potvrzení“: omylem se ohodnotit nedá jedním kliknutím, a kdyby přece, jde to zrušit.
Souhrn („👍 3 · 😐 1“) je nevýrazně pod jídlem ve výpisu, počítá se přes všechny dny, kdy se jídlo vařilo.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from datetime import datetime

import discord
from discord.ext import commands

from lunch import kam, service
from lunch.models import Category, Menu
from storage import DatabaseUnavailable, ratings, ready
from storage import menus as stored_menus
from utils.interactions import STALE, reported

log = logging.getLogger(__name__)

RESTAURANTS = "rest"  # rozsah „restaurace“ v custom_id, jinak klíč skupiny menz (kam.GROUPS)
MAX_OPTIONS = 25  # limit Discordu na výběr
NOTHING = "Dnes tu zatím není co hodnotit 🤷"
SCORE_KEYS = {"g": ratings.GOOD, "o": ratings.OK, "b": ratings.BAD}
SCORE_STYLES = {
    ratings.GOOD: discord.ButtonStyle.success,
    ratings.OK: discord.ButtonStyle.secondary,
    ratings.BAD: discord.ButtonStyle.danger,
}


def _db(client) -> stored_menus.Database | None:
    return getattr(client, "db", None)


async def rating_notes(client, menus: Iterable[Menu]) -> dict[str, dict[str, str]]:
    """Souhrny hodnocení do výpisu: {podnik: {název jídla: „👍 3 · 😐 1“}}. Bez databáze prázdné (nic se neukáže)."""
    db = _db(client)
    if not ready(db):
        return {}
    names = {
        (m.place.key, d.name[: stored_menus.NAME_LIMIT]): d.name
        for m in menus for d in m.dishes if d.category is Category.MAIN
    }
    try:
        found = await ratings.summaries(db, names)
    except Exception:
        log.exception("Načtení hodnocení jídel selhalo")
        return {}
    notes: dict[str, dict[str, str]] = {}
    for (place, short), summary in found.items():
        notes.setdefault(place, {})[names[(place, short)]] = summary.text()
    return notes


async def _menus(client, scope: str) -> list[Menu] | None:
    if scope == RESTAURANTS:
        return await service.restaurant_menus(client.fetcher)
    if scope in kam.GROUPS:
        return await service.menza_menus(client.fetcher, scope)
    return None


def _describe(dish: stored_menus.StoredDish, place: str) -> str:
    return " · ".join(p for p in (place, dish.label, f"{dish.price} Kč" if dish.price else None) if p)


async def dish_picker(client, user_id: int, scope: str) -> tuple[str, discord.ui.View | None]:
    """Text a výběr dnešních jídel k ohodnocení (hlavní jídla první, polévky jen když se vejdou)."""
    menus = await _menus(client, scope)
    if menus is None:
        return STALE, None
    db = _db(client)
    if db is None:
        raise DatabaseUnavailable("Bot nemá databázi")
    await stored_menus.remember(db, menus)  # ať jsou v databázi i jídla, která obnova na pozadí ještě neuložila
    places = {m.place.key: m.place for m in menus}
    dishes = await stored_menus.for_day(db, service.today(), places)
    order = list(places)
    dishes.sort(key=lambda d: (d.category != "main", d.group is not None, order.index(d.place), d.id))
    dishes = dishes[:MAX_OPTIONS]
    if not dishes:
        return NOTHING, None
    mine = await ratings.scores_of(db, user_id, (d.id for d in dishes))
    options = []
    for d in dishes:
        place = places[d.place]
        description = _describe(d, place.name)
        if d.id in mine:
            description = f"{description} · tvoje: {ratings.SCORES[mine[d.id]][0]}"
        options.append(discord.SelectOption(
            label=d.name[:100], value=str(d.id), description=description[:100], emoji=place.emoji,
        ))
    view = discord.ui.View(timeout=None)
    view.add_item(DishSelect(options))
    return "⭐ **Co sis dal(a)?** Vyber jídlo a pak ho ohodnoť.", view


def vote_message(dish: stored_menus.StoredDish, current: int | None = None) -> tuple[str, discord.ui.View]:
    place = kam.MENZY.get(dish.place) or next(
        (r.place for r in service.RESTAURANTS if r.place.key == dish.place), None
    )
    info = _describe(dish, place.name if place else dish.place)
    content = f"**{dish.name}**\n-# {info}\nJak ti chutnalo?"
    view = discord.ui.View(timeout=None)
    for key, score in SCORE_KEYS.items():
        icon, label = ratings.SCORES[score]
        view.add_item(VoteButton(dish.id, key, label=label, emoji=icon, style=SCORE_STYLES[score]))
    if current is not None:
        content += f"\n-# Teď máš: {' '.join(ratings.SCORES[current])}"
    return content, view


class RateButton(discord.ui.DynamicItem[discord.ui.Button], template=r"znamka:o:(?P<scope>[a-z]+)"):
    """⭐ Ohodnotit pod výpisem jídel. `scope` = skupina menz nebo `rest` (restaurace)."""

    def __init__(self, scope: str, row: int | None = None) -> None:
        super().__init__(discord.ui.Button(
            custom_id=f"znamka:o:{scope}", label="Ohodnotit", emoji="⭐", style=discord.ButtonStyle.secondary, row=row,
        ))
        self.scope = scope

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> RateButton:
        return cls(match["scope"])

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        content, view = await dish_picker(interaction.client, interaction.user.id, self.scope)
        if view is None:
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.followup.send(content, view=view, ephemeral=True)


class DishSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"znamka:s"):
    def __init__(self, options: list[discord.SelectOption] | None = None) -> None:
        super().__init__(discord.ui.Select(custom_id="znamka:s", placeholder="🍽️ Vyber jídlo", options=options or []))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> DishSelect:
        return cls()

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.item.values[0] if self.item.values else ""
        db = _db(interaction.client)
        dish = await stored_menus.get(db, int(value)) if value.isdigit() and db else None
        if dish is None:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        current = (await ratings.scores_of(db, interaction.user.id, [dish.id])).get(dish.id)
        content, view = vote_message(dish, current)
        await interaction.response.edit_message(content=content, view=view)


class VoteButton(discord.ui.DynamicItem[discord.ui.Button], template=r"znamka:h:(?P<dish>\d+):(?P<score>[gob])"):
    def __init__(self, dish_id: int, score: str, **button_kwargs) -> None:
        super().__init__(discord.ui.Button(custom_id=f"znamka:h:{dish_id}:{score}", **button_kwargs))
        self.dish_id = dish_id
        self.score = score

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> VoteButton:
        return cls(int(match["dish"]), match["score"])

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        db = _db(interaction.client)
        dish = await stored_menus.get(db, self.dish_id) if db else None
        if dish is None:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        score = SCORE_KEYS[self.score]
        await ratings.rate(db, dish.id, interaction.user.id, score, datetime.now(service.TZ))
        icon, label = ratings.SCORES[score]
        view = discord.ui.View(timeout=None)
        view.add_item(UndoButton(dish.id))
        await interaction.response.edit_message(
            content=f"✅ Uloženo: {icon} **{label}** – {dish.name}\n-# Souhrn se ukáže u jídla ve výpisu po obnovení.",
            view=view,
        )


class UndoButton(discord.ui.DynamicItem[discord.ui.Button], template=r"znamka:z:(?P<dish>\d+)"):
    def __init__(self, dish_id: int) -> None:
        super().__init__(discord.ui.Button(
            custom_id=f"znamka:z:{dish_id}", label="Zrušit", emoji="↩️", style=discord.ButtonStyle.secondary,
        ))
        self.dish_id = dish_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> UndoButton:
        return cls(int(match["dish"]))

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        db = _db(interaction.client)
        dish = await stored_menus.get(db, self.dish_id) if db else None
        if dish is None:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        await ratings.unrate(db, dish.id, interaction.user.id)
        content, view = vote_message(dish)
        await interaction.response.edit_message(content=f"↩️ Hodnocení zrušeno.\n{content}", view=view)


ITEMS = (RateButton, DishSelect, VoteButton, UndoButton)


class Hodnoceni(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(*ITEMS)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(*ITEMS)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Hodnoceni(bot))
