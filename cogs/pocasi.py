"""/pocasi – počasí u FITu a kolejí (Open-Meteo), obnovuje se na pozadí."""

from __future__ import annotations

import logging
import re
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from lunch.service import today
from utils import loading, render
from weather import openmeteo

log = logging.getLogger(__name__)

REFRESH_MINUTES = 15
TTL = 20 * 60  # delší než interval obnovy, ať command nestahuje sám
STEP_HOURS = 3  # kartičky po 3 hodinách
CARDS = 6  # = příštích 18 hodin
DAY_NAMES = ["Dnes", "Zítra"]


def _deg(t: float) -> str:
    return f"{round(t)} °C".replace("-", "−")


def _hm(d: datetime) -> str:
    return f"{d.hour}:{d.minute:02d}"


def weather_embed(f: openmeteo.Forecast) -> discord.Embed:
    icon, text = openmeteo.describe(f.code, f.is_day)
    lines = [
        f"## {icon} {_deg(f.temperature)}",
        f"{text} · pocitově {_deg(f.feels_like)} · vítr {round(f.wind)} km/h",
    ]
    tips = openmeteo.advice(f)
    if tips:
        lines.append("\n💡 " + " · ".join(tips))
    window = openmeteo.window_advice(f)
    if window:
        lines.append(f"🪟 **Okno přes noc:** {window}")
    embed = discord.Embed(title=f"Počasí – {openmeteo.PLACE}", url=openmeteo.SOURCE_URL, description="\n".join(lines),
                          color=0x339AF0)

    fields = []
    for h in f.hours[STEP_HOURS::STEP_HOURS][:CARDS]:
        h_icon, _ = openmeteo.describe(h.code, h.is_day)
        rain = f"\n💧 {h.rain_chance} %" if h.rain_chance else ""
        fields.append(render.Field(f"🕐 {h.time.hour}:00", f"{h_icon} {_deg(h.temperature)}{rain}"))
    day_lines = []
    for name, d in zip(DAY_NAMES, f.days):
        d_icon, d_text = openmeteo.describe(d.code)
        rain = f" · 💧 {d.rain_chance} %" if d.rain_chance else ""
        day_lines.append(f"**{name}** {d_icon} {_deg(d.t_min)} až {_deg(d.t_max)}, {d_text}{rain}")
    if f.days:
        day_lines.append(f"🌅 {_hm(f.days[0].sunrise)} · 🌇 {_hm(f.days[0].sunset)}")
    fields.append(render.Field("📅 Dnes a zítra", "\n".join(day_lines), inline=False))
    render.add_fields(embed, fields, 4000)
    embed.set_footer(text="Data: Open-Meteo.com (CC BY 4.0)")
    return embed


async def build_message(fetcher, force: bool = False) -> tuple[str, list[discord.Embed], discord.ui.View]:
    text, fetched = await fetcher.get(openmeteo.URL, ttl=TTL, force=force)
    forecast = openmeteo.parse(text)
    content = (
        f"### ☀️ Počasí v Brně – {render.czech_date(today())}\n"
        f"-# aktualizováno <t:{int(fetched)}:R>"
    )
    return content, [weather_embed(forecast)], build_view()


class PocasiButton(discord.ui.DynamicItem[discord.ui.Button], template=r"pocasi:r"):
    def __init__(self) -> None:
        super().__init__(
            discord.ui.Button(custom_id="pocasi:r", label="Obnovit", emoji="🔄", style=discord.ButtonStyle.secondary)
        )

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> PocasiButton:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        content, embeds, view = await build_message(interaction.client.fetcher, force=True)
        await interaction.edit_original_response(content=content, embeds=embeds, view=view)


def build_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(PocasiButton())
    view.add_item(discord.ui.Button(label="Open-Meteo", url=openmeteo.SOURCE_URL))
    return view


class Pocasi(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(PocasiButton)
        if getattr(self.bot, "background_refresh", True):
            self.prefetch.start()
            loading.expect(self.bot, "počasí")

    async def cog_unload(self) -> None:
        self.prefetch.cancel()
        self.bot.remove_dynamic_items(PocasiButton)

    @tasks.loop(minutes=REFRESH_MINUTES)
    async def prefetch(self) -> None:
        """Předpověď na pozadí, ať /pocasi odpovídá hned."""
        try:
            async with loading.track(self.bot, "počasí"):
                await self.bot.fetcher.get(openmeteo.URL, ttl=TTL, force=True)
        except Exception:
            log.exception("Obnova počasí selhala")

    @app_commands.command(name="pocasi", description="☀️ Počasí u FITu a kolejí: teď, dalších 18 hodin, dnes a zítra")
    async def pocasi(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        try:
            content, embeds, view = await build_message(self.bot.fetcher)
        except Exception:
            log.exception("Načtení počasí selhalo")
            await interaction.followup.send("Počasí se teď nepodařilo načíst 😵 Zkus to za chvíli.")
            return
        await interaction.followup.send(content=content, embeds=embeds, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Pocasi(bot))
