"""/otevreno – co má teď otevřeno: menzy, pizzerie a kavárny VUT a okolní obchody.

Otevírací doby už bot má: KaM je má v přehledu `?p=otdo` (stahuje se kvůli menzám) a obchody v JSON-LD
stránek poboček na Kupi.cz (stahuje se kvůli letákům). Nic dalšího se kvůli /otevreno nestahuje.
Ve svátky mají velké obchody ze zákona zavřeno (utils.holidays), to Kupi.cz neví.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from lunch import kam, service
from shops import kupi
from shops.service import STORES, Shops
from utils import holidays, opening, render
from utils.opening import Interval, State

log = logging.getLogger(__name__)

COLOR_FOOD = 0x2B8A3E
COLOR_SHOPS = 0x1971C2
STATE_ORDER = {State.CLOSING_SOON: 0, State.OPEN: 0, State.LATER: 1, State.CLOSED: 2}

# Provozy KaM, kam studenti nechodí (jen pro zaměstnance)
_STAFF_RE = re.compile(r"zaměstnan", re.IGNORECASE)
# Emoji podle druhu provozu (menzy, které bot zná, mají svoje z kam.MENZY)
_KIND_EMOJI = [("pizzer", "🍕"), ("kav", "☕"), ("caff", "☕"), ("bufet", "🥪")]


@dataclass(frozen=True)
class Spot:
    """Jedno místo s otevírací dobou (dnes a zítra)."""

    name: str
    emoji: str
    today: list[Interval]
    tomorrow: list[Interval]
    note: str | None = None  # proč je dnes zavřeno (akce, svátek…)


def _provoz_emoji(p: kam.Provoz) -> str:
    known = {m.provoz: m.emoji for m in kam.MENZY.values()}
    if p.provoz in known:
        return known[p.provoz]
    lower = p.name.lower()
    return next((e for key, e in _KIND_EMOJI if key in lower), "🍽️")


def food_spots(provozy: list[kam.Provoz], day: date) -> list[Spot]:
    """Provozy KaM pro studenty. Ty bez jakékoliv otevírací doby (mimo provoz) se vynechají."""
    spots = []
    for p in provozy:
        if _STAFF_RE.search(p.name) or not any(p.columns):
            continue
        today = [] if p.closed_note else p.intervals(day)
        spots.append(Spot(p.name, _provoz_emoji(p), today, p.intervals(day + timedelta(days=1)), p.closed_note))
    return spots


def shop_intervals(page: kupi.StorePage | None, day: date) -> tuple[list[Interval], str | None]:
    """Otevírací doba pobočky v daný den, včetně zákonem zavřených svátků (Kupi.cz je nezná)."""
    intervals = opening.parse_intervals(page.hours.get(day.weekday())) if page else []
    if holidays.shops_closed(day):
        return [], "svátek"
    if close := holidays.shops_close_early(day):
        cut = opening.minutes(close)
        clipped = [(a, b if opening.minutes(b) <= cut else close) for a, b in intervals if opening.minutes(a) < cut]
        return clipped, "Štědrý den"
    return intervals, None


def shop_spots(pages: dict[str, kupi.StorePage | None], day: date) -> list[Spot]:
    spots = []
    for store in STORES.values():
        name = store.name.removesuffix(" supermarket")  # „Albert Semilasso (Kosmova)“ stačí
        for branch in store.branches:
            page = pages.get(branch.kupi_path)
            if page is None or not page.hours:
                continue
            today, note = shop_intervals(page, day)
            tomorrow, _ = shop_intervals(page, day + timedelta(days=1))
            spots.append(Spot(f"{name} {branch.label}", store.emoji, today, tomorrow, note))
    return spots


_STATE_TEXT = {State.OPEN: "🟢 do", State.CLOSING_SOON: "🟡 zavírá v", State.LATER: "🕐 otevře v"}


def _status_text(spot: Spot, s: opening.Status) -> str:
    """'🟢 do **14:30** · za 2 hodiny' / '🔴 zavřeno' + nevýrazně zítřejší doba."""
    if s.at is not None:
        return f"{_STATE_TEXT[s.state]} **{s.at.hour}:{s.at:%M}** · <t:{int(s.at.timestamp())}:R>"
    closed = f"🔴 zavřeno ({spot.note})" if spot.note else "🔴 zavřeno"
    return f"{closed}\n-# zítra {s.tomorrow}"


def spot_fields(spots: list[Spot], now: datetime) -> list[render.Field]:
    """Kartičky seřazené podle stavu: otevřené, dnes ještě otevřou, zavřené (jinak v pořadí jako ve zdroji)."""
    rated = [(spot, opening.status(now, spot.today, spot.tomorrow)) for spot in spots]
    rated.sort(key=lambda sr: STATE_ORDER[sr[1].state])
    return [render.Field(f"{spot.emoji} {spot.name}", _status_text(spot, s)) for spot, s in rated]


def _section(title: str, url: str, color: int, fields: list[render.Field], empty: str, footer: str | None) -> discord.Embed:
    embed = discord.Embed(title=title, url=url, color=color)
    if fields:
        render.add_fields(embed, fields, 2800)
    else:
        embed.description = f"⚠️ {empty}"
    if footer:
        embed.set_footer(text=footer)
    return embed


def _shops_footer(day: date) -> str:
    if holidays.shops_closed(day):
        return "Dnes je svátek: obchody nad 200 m² mají ze zákona zavřeno."
    if holidays.shops_close_early(day):
        return "Na Štědrý den mají obchody nad 200 m² ze zákona otevřeno jen do 12:00."
    return "Otevírací doba poboček z Kupi.cz"


async def build_message(
    fetcher, shops: Shops | None, force: bool = False, now: datetime | None = None
) -> tuple[str, list[discord.Embed], discord.ui.View]:
    now = now or datetime.now(service.TZ)
    day = now.date()
    try:
        food = food_spots(await service.kam_overview(fetcher, force), day)
    except Exception:
        log.exception("Načtení otevíracích dob KaM selhalo")
        food = []
    try:
        pages = await shops.store_pages(force) if shops else {}
    except Exception:
        log.exception("Načtení otevíracích dob obchodů selhalo")
        pages = {}

    embeds = [
        _section("🍽️ Menzy a kavárny VUT", kam.OVERVIEW_URL, COLOR_FOOD, spot_fields(food, now),
                 "Otevírací doby menz se nepodařilo načíst.", "Otevírací doby z webu KaM VUT"),
        _section("🛒 Obchody", kupi.BASE, COLOR_SHOPS, spot_fields(shop_spots(pages, day), now),
                 "Otevírací doby obchodů se nepodařilo načíst.", _shops_footer(day)),
    ]
    ts = int(now.timestamp())
    content = f"### 🕐 Co je otevřeno – {render.czech_date(day)}\n-# Stav v <t:{ts}:t>. Tlačítkem 🔄 se přepočítá."
    return content, embeds, build_view()


class OtevrenoButton(discord.ui.DynamicItem[discord.ui.Button], template=r"otevreno:r"):
    def __init__(self) -> None:
        super().__init__(discord.ui.Button(custom_id="otevreno:r", label="Obnovit", emoji="🔄",
                                           style=discord.ButtonStyle.secondary))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> OtevrenoButton:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        content, embeds, view = await build_message(interaction.client.fetcher, _shops(interaction.client))
        await interaction.edit_original_response(content=content, embeds=embeds, view=view)


def build_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(OtevrenoButton())
    view.add_item(discord.ui.Button(label="Web KaM", url=kam.OVERVIEW_URL))
    return view


def _shops(client) -> Shops | None:
    """Obchody si drží cog Slevy (stahuje je na pozadí kvůli letákům)."""
    cog = client.get_cog("Slevy")
    return cog.shops if cog else None


class Otevreno(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(OtevrenoButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(OtevrenoButton)

    @app_commands.command(name="otevreno", description="🕐 Co má teď otevřeno: menzy, kavárny a bufety VUT, obchody")
    async def otevreno(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        content, embeds, view = await build_message(self.bot.fetcher, _shops(self.bot))
        await interaction.followup.send(content=content, embeds=embeds, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Otevreno(bot))
