"""/obed – kdo jde na oběd? Hlasování tlačítky: kam (menza / restaurace) a v kolik.

Stav hlasování se neukládá nikam bokem – je přímo v embedu zprávy (kdo je u kterého místa a v kolik).
Tlačítka ho při kliknutí přečtou, upraví a zprávu přepíšou. Funguje to tak i po restartu bota.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from lunch import kam, service
from utils import render


@dataclass(frozen=True)
class Spot:
    key: str
    label: str
    emoji: str


# Místa k výběru: menzy a restaurace, které bot zná (krátké názvy na tlačítka).
SPOTS: dict[str, Spot] = {
    s.key: s
    for s in [
        Spot("kolejni", "Kolejní", kam.MENZY["kolejni"].emoji),
        Spot("mozzarella", "Mozzarella", kam.MENZY["mozzarella"].emoji),
        Spot("stary_pivovar", "Starý pivovar", kam.MENZY["stary_pivovar"].emoji),
        Spot("purkynova", "Purkyňova", kam.MENZY["purkynova"].emoji),
        *(Spot(r.place.key, r.place.name, r.place.emoji) for r in service.RESTAURANTS),
    ]
}
TIMES = ("11:00", "11:30", "12:00", "12:30", "13:00")
COLOR = 0xF08C00

_FIELD_NAME_RE = re.compile(r"\(\d+\)$")
_ENTRY_RE = re.compile(r"<@(\d+)>(?: · (.+))?")
_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)  # zpráva -> zámek (dvě kliknutí naráz)


# --- stav: {user_id: (spot_key, čas | None)} ------------------------------------------------------


def read_state(embed: discord.Embed | None) -> dict[int, tuple[str, str | None]]:
    state: dict[int, tuple[str, str | None]] = {}
    if embed is None:
        return state
    by_title = {f"{s.emoji} {s.label}": s.key for s in SPOTS.values()}
    for field in embed.fields:
        title = _FIELD_NAME_RE.sub("", field.name).strip()
        key = by_title.get(title)
        if key is None:
            continue
        for line in field.value.splitlines():
            m = _ENTRY_RE.search(line)
            if m:
                state[int(m.group(1))] = (key, m.group(2))
    return state


def creator_of(embed: discord.Embed | None) -> str:
    m = re.search(r"Svolává <@(\d+)>", embed.description or "") if embed else None
    return m.group(1) if m else ""


def build_embed(state: dict[int, tuple[str, str | None]], creator: str) -> discord.Embed:
    lines = []
    if creator:
        lines.append(f"Svolává <@{creator}>")
    lines.append("Klikni, kam jdeš, a vyber čas. Druhé kliknutí na stejné místo tě odhlásí.")
    if not state:
        lines.append("\n_Zatím nikdo…_ 🦗")
    embed = discord.Embed(
        title=f"🍽️ Kdo jde na oběd? – {render.czech_date(service.today())}",
        description="\n".join(lines),
        color=COLOR,
    )
    by_spot: dict[str, list[tuple[int, str | None]]] = defaultdict(list)
    for user, (spot, time) in state.items():
        by_spot[spot].append((user, time))
    fields = []
    for key, spot in SPOTS.items():
        people = sorted(by_spot.get(key, []), key=lambda p: (p[1] or "99", p[0]))
        if people:
            value = "\n".join(f"<@{u}>" + (f" · {t}" if t else "") for u, t in people)
            fields.append(render.Field(f"{spot.emoji} {spot.label} ({len(people)})", value))
    render.add_fields(embed, fields, 5000)
    return embed


def apply(state: dict[int, tuple[str, str | None]], user: int, action: str, arg: str, now: datetime) -> str | None:
    """Upraví stav podle kliknutí. Vrací hlášku pro uživatele (jen jemu), nebo None."""
    current = state.get(user)
    if action == "p":
        if current and current[0] == arg:
            del state[user]  # druhé kliknutí na stejné místo = odhlášení
        else:
            state[user] = (arg, current[1] if current else None)
    elif action in ("t", "now"):
        if not current:
            return "Nejdřív vyber, kam jdeš. 🙂"
        time = f"🚶 {now:%H:%M}" if action == "now" else f"{arg[:2]}:{arg[2:]}"
        state[user] = (current[0], time)
    elif action == "x":
        state.pop(user, None)
    return None


# --- tlačítka -----------------------------------------------------------------------------------


class ObedButton(discord.ui.DynamicItem[discord.ui.Button], template=r"obed:(?P<action>p|t|now|x)(?::(?P<arg>[a-z0-9_]+))?"):
    """p:<místo> = jdu sem, t:<HHMM> = v tolik, now = jdu teď, x = nejdu"""

    def __init__(self, action: str, arg: str = "", **button_kwargs) -> None:
        custom_id = f"obed:{action}" + (f":{arg}" if arg else "")
        super().__init__(discord.ui.Button(custom_id=custom_id, **button_kwargs))
        self.action = action
        self.arg = arg

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> ObedButton:
        return cls(match["action"], match["arg"] or "")

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.action == "p" and self.arg not in SPOTS:
            await interaction.response.send_message("Tohle tlačítko už je zastaralé.", ephemeral=True)
            return
        message = interaction.message
        async with _locks[message.id]:
            embed = message.embeds[0] if message.embeds else None
            state = read_state(embed)
            error = apply(state, interaction.user.id, self.action, self.arg, datetime.now(service.TZ))
            if error:
                await interaction.response.send_message(error, ephemeral=True)
                return
            await interaction.response.edit_message(embed=build_embed(state, creator_of(embed)), view=build_view())


class ObedNewButton(discord.ui.DynamicItem[discord.ui.Button], template=r"obed:new"):
    """Tlačítko "Svolat oběd" pod výpisem menz a restaurací – pošle nové hlasování jako /obed."""

    def __init__(self, row: int | None = None) -> None:
        super().__init__(
            discord.ui.Button(custom_id="obed:new", label="Svolat oběd", emoji="🍽️",
                              style=discord.ButtonStyle.success, row=row)
        )

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> ObedNewButton:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=build_embed({}, str(interaction.user.id)), view=build_view())


def build_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for i, spot in enumerate(SPOTS.values()):
        view.add_item(ObedButton("p", spot.key, label=spot.label, emoji=spot.emoji,
                                 style=discord.ButtonStyle.secondary, row=i // 5))
    for t in TIMES:
        view.add_item(ObedButton("t", t.replace(":", ""), label=t, emoji="🕐",
                                 style=discord.ButtonStyle.primary, row=2))
    view.add_item(ObedButton("now", label="Jdu teď", emoji="🚶", style=discord.ButtonStyle.success, row=3))
    view.add_item(ObedButton("x", label="Nejdu", emoji="❌", style=discord.ButtonStyle.danger, row=3))
    return view


class Obed(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(ObedButton, ObedNewButton)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(ObedButton, ObedNewButton)

    @app_commands.command(name="obed", description="🍽️ Kdo jde na oběd? Hlasování, kam a v kolik")
    async def obed(self, interaction: discord.Interaction) -> None:
        embed = build_embed({}, str(interaction.user.id))
        await interaction.response.send_message(embed=embed, view=build_view())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Obed(bot))
