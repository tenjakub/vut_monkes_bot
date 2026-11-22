"""/kola – volná sdílená kola nextbike na stanicích u kolejí PPV, u Purkyní a u FITu."""

from __future__ import annotations

import logging
import re
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from bikes import nextbike
from bikes.service import AREAS, REFRESH_MINUTES, Bikes, Snapshot
from lunch.service import TZ
from utils import loading, render

log = logging.getLogger(__name__)

COLOR = 0x1C7ED6
STALE = "Tohle tlačítko už je zastaralé."


def bikes_text(n: int) -> str:
    """0 kol, 1 kolo, 2 kola, 5 kol."""
    if n == 1:
        return "1 kolo"
    return f"{n} kola" if 2 <= n <= 4 else f"{n} kol"


def _distance_text(meters: float) -> str:
    return f"{round(meters / 10) * 10} m" if meters < 1000 else f"{meters / 1000:.1f} km".replace(".", ",")


def _short_name(name: str) -> str:
    """'VUT - Koleje a menzy (Pod Palackého vrchem)' -> 'Koleje a menzy (Pod Palackého vrchem)'."""
    return re.sub(r"^VUT\s*-\s*", "", name)


def station_field(n: nextbike.Nearby) -> render.Field:
    if not n.renting:
        head = "⛔ mimo provoz"
    elif n.bikes:
        head = f"🚲 **{bikes_text(n.bikes)}**"
    else:
        head = "⚪ žádné kolo"
    walk = f"-# 🚶 {_distance_text(n.distance)} · {n.walk_minutes} min"
    return render.Field(_short_name(n.station.name)[:256], f"[{head}]({n.station.url})\n{walk}")


def bikes_embed(snap: Snapshot) -> discord.Embed:
    embed = discord.Embed(title=f"🚲 nextbike {snap.area.label}", url=nextbike.SOURCE_URL, color=COLOR)
    if snap.stations:
        render.add_fields(embed, [station_field(n) for n in snap.stations], 4000)
    else:
        embed.description = "_V okolí není žádná stanice._"
    if snap.nearest:
        n = snap.nearest
        embed.add_field(
            name="👀 Nejbližší kolo dál",
            value=f"[{n.station.name}]({n.station.url}) · {bikes_text(n.bikes)} · 🚶 {_distance_text(n.distance)}",
            inline=False,
        )
    embed.set_footer(text=f"Stanice do {_distance_text(snap.area.radius)} · data: nextbike (CC0)")
    return embed


def summary(snap: Snapshot) -> str:
    with_bikes = sum(1 for n in snap.stations if n.bikes)
    if not snap.total:
        return "😕 V okolí teď není žádné volné kolo"
    stations = "stanici" if with_bikes == 1 else "stanicích"
    return f"🚲 **{bikes_text(snap.total)}** na {with_bikes} {stations}"


async def build_message(bikes: Bikes, area: str, force: bool = False) -> tuple[str, list[discord.Embed], discord.ui.View]:
    snap = await bikes.snapshot(area, force)
    info = [summary(snap)]
    if snap.updated:
        info.append(f"aktualizováno <t:{snap.updated}:R>")
    day = datetime.now(TZ).date()
    content = f"### 🚲 Kola {snap.area.label} – {render.czech_date(day)}\n" + " · ".join(info)
    return content, [bikes_embed(snap)], build_view(area)


class KolaButton(discord.ui.DynamicItem[discord.ui.Button], template=r"kola:(?P<area>[a-z_]+):(?P<slot>[gr])"):
    """slot: g = přepnutí oblasti, r = obnovit"""

    def __init__(self, area: str, slot: str, **button_kwargs) -> None:
        super().__init__(discord.ui.Button(custom_id=f"kola:{area}:{slot}", **button_kwargs))
        self.area = area
        self.slot = slot

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> KolaButton:
        return cls(match["area"], match["slot"])

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.area not in AREAS:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        await interaction.response.defer()
        content, embeds, view = await build_message(_bikes(interaction.client), self.area, force=self.slot == "r")
        await interaction.edit_original_response(content=content, embeds=embeds, view=view)


def build_view(area: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for a in AREAS.values():
        current = a.key == area
        view.add_item(KolaButton(a.key, "g", label=a.button, disabled=current,
                                 style=discord.ButtonStyle.primary if current else discord.ButtonStyle.secondary))
    view.add_item(KolaButton(area, "r", label="Obnovit", emoji="🔄", style=discord.ButtonStyle.secondary))
    view.add_item(discord.ui.Button(label="nextbike", url=nextbike.SOURCE_URL))
    return view


def _bikes(client) -> Bikes:
    return client.get_cog("Kola").bikes


class Kola(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.bikes = Bikes(bot.fetcher)

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(KolaButton)
        if getattr(self.bot, "background_refresh", True):
            self.refresh.start()
            loading.expect(self.bot, "kola nextbike")

    async def cog_unload(self) -> None:
        self.refresh.cancel()
        self.bot.remove_dynamic_items(KolaButton)

    @tasks.loop(minutes=REFRESH_MINUTES)
    async def refresh(self) -> None:
        """Stav stanic na pozadí, ať /kola odpovídá hned."""
        try:
            async with loading.track(self.bot, "kola nextbike"):
                await self.bikes.refresh()
        except Exception:
            log.exception("Obnova kol nextbike selhala")

    @app_commands.command(name="kola", description="🚲 Volná kola nextbike u kolejí PPV (tlačítky i u Purkyní a FITu)")
    async def kola(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            content, embeds, view = await build_message(self.bikes, "ppv")
        except Exception:
            log.exception("Načtení kol nextbike selhalo")
            await interaction.followup.send("Kola se teď nepodařilo načíst 😵 Zkus to za chvíli.")
            return
        await interaction.followup.send(content=content, embeds=embeds, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Kola(bot))
