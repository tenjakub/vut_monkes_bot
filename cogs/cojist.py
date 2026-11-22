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
from utils.interactions import STALE, reported

log = logging.getLogger(__name__)

# rozsah: (emoji, popisek tlačítka)
SCOPES: dict[str, tuple[str, str]] = {
    "vse": ("🌍", "Všude"),
    "menzy": ("🏫", "Menzy"),
    "economy": ("💰", "Jen Economy"),
    "restaurace": ("🍴", "Restaurace"),
}
MAX_PRICE = 150  # Kč – přepínač "Do 150 Kč", ve výchozím stavu vypnutý
_PRICE_RE = re.compile(r"\d+(?:[.,]\d+)?")


def price_value(price: str) -> float | None:
    """'159 Kč' -> 159.0; bez čísla None."""
    m = _PRICE_RE.search(price.replace("\u00a0", "").replace(" ", ""))
    return float(m.group().replace(",", ".")) if m else None


def affordable(dish: Dish, max_price: float = MAX_PRICE) -> bool:
    """Jídlo bez uvedené ceny se nevyřazuje (nevíme, kolik stojí)."""
    value = price_value(dish.price or "")
    return value is None or value <= max_price


@dataclass(frozen=True)
class Pick:
    dish: Dish
    menu: Menu
    menza: bool


async def candidates(fetcher, scope: str, cheap: bool = False) -> list[Pick]:
    """Hlavní jídla (bez polévek) z dnešních výpisů; data jdou z cache obnovované na pozadí.
    cheap = jen do MAX_PRICE Kč."""
    picks: list[Pick] = []
    if scope in ("vse", "menzy", "economy"):
        for menu in await service.menza_menus(fetcher, "vse"):
            for d in menu.mains:
                if scope != "economy" or d.economy:
                    picks.append(Pick(d, menu, True))
    if scope in ("vse", "restaurace"):
        for menu in await service.restaurant_menus(fetcher):
            picks += [Pick(d, menu, False) for d in menu.mains]
    if cheap:
        picks = [p for p in picks if affordable(p.dish)]
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
        description=f"_{d.description}_" if d.description else None,  # přísady (pizzy v Sesamu)
    )
    embed.add_field(name="📍 Kde", value=f"{place.emoji} {place.name}", inline=True)
    if d.price:
        embed.add_field(name="💸 Cena", value=d.price + (" (student)" if pick.menza else ""), inline=True)
    if pick.menu.hours:
        embed.add_field(name="🕐 Otevřeno", value=pick.menu.hours, inline=True)
    return embed


async def build_message(
    bot: commands.Bot, scope: str, cheap: bool = False
) -> tuple[str, list[discord.Embed], discord.ui.View]:
    picks = await candidates(bot.fetcher, scope, cheap)
    icon, label = SCOPES[scope]
    header = f"### 🎲 Co dneska jíst? – {render.czech_date(service.today())}"
    limit = f" · 💸 do {MAX_PRICE} Kč" if cheap else ""
    if not picks:
        reason = f"nic do {MAX_PRICE} Kč" if cheap else "nic"
        content = f"{header}\n_Dnes tu ({label.lower()}) {reason} není. Asi se nevaří, nebo je zavřeno._ 😢"
        return content, [], build_view(scope, cheap)
    pick = random.choice(picks)
    dishes = "jídla" if len(picks) == 1 else "jídel"
    content = f"{header}\n-# Náhodně z {len(picks)} {dishes} · {icon} {label}{limit}"
    return content, [pick_embed(pick)], build_view(scope, cheap)


class CojistButton(
    discord.ui.DynamicItem[discord.ui.Button], template=r"cojist:(?P<scope>[a-z]+):(?P<slot>[rsc])(?::(?P<cheap>[01]))?"
):
    """slot: r = znovu losovat ve stejném rozsahu, s = přepnout rozsah (a losovat), c = zapnout/vypnout limit ceny.
    cheap = 1/0 jen do MAX_PRICE Kč; starší tlačítka ho nemají -> vypnuto (výchozí stav)."""

    def __init__(self, scope: str, slot: str, cheap: bool = False, **button_kwargs) -> None:
        super().__init__(discord.ui.Button(custom_id=f"cojist:{scope}:{slot}:{int(cheap)}", **button_kwargs))
        self.scope = scope
        self.cheap = cheap

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> CojistButton:
        return cls(match["scope"], match["slot"], match["cheap"] == "1")

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        if self.scope not in SCOPES:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        await interaction.response.defer()
        content, embeds, view = await build_message(interaction.client, self.scope, self.cheap)
        await interaction.edit_original_response(content=content, embeds=embeds, view=view)


def build_view(scope: str, cheap: bool = False) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(CojistButton(scope, "r", cheap, label="Znovu", emoji="🎲", style=discord.ButtonStyle.success, row=0))
    for key, (icon, label) in SCOPES.items():
        current = key == scope
        view.add_item(
            CojistButton(
                key, "s", cheap, label=label, emoji=icon, disabled=current,
                style=discord.ButtonStyle.primary if current else discord.ButtonStyle.secondary, row=0,
            )
        )
    # přepínač: zelený = zapnuto, šedý = vypnuto (jako "Jen se slevou" u slev)
    view.add_item(
        CojistButton(
            scope, "c", not cheap, label=f"Do {MAX_PRICE} Kč", emoji="💸", row=1,
            style=discord.ButtonStyle.success if cheap else discord.ButtonStyle.secondary,
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
