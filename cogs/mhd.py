"""/mhd – odjezdy MHD z vybraných zastávek podle jízdního řádu IDS JMK + aktuální výluky."""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands, tasks

from transit import alerts as alerts_mod
from transit.gtfs import TZ, Departure, Timetable
from transit.service import BOARDS, GROUPS, MERGED_LINES, Board, Transit
from utils import render

log = logging.getLogger(__name__)

DEPARTURES_URL = "https://www.idsjmk.cz/departures/index"
PER_CARD = 4  # kolik nejbližších odjezdů ukázat v jedné kartičce
MAX_CARDS = 12
MAX_ALERTS = 3

GROUP_LABELS = {"vse": "Obě zastávky", **{k: b.name for k, b in BOARDS.items()}}


def _time_row(d: Departure, bold: bool = True, tag: str | None = None) -> str:
    time = f"**{d.when:%H:%M}**" if bold else f"{d.when:%H:%M}"
    row = f"{time} · <t:{int(d.when.timestamp())}:R>"
    return f"{row} · `{tag}`" if tag else row


def _cards(departures: list[Departure], merged: tuple[tuple[str, ...], ...] = MERGED_LINES) -> list[render.Field]:
    """Kartičky s nejbližšími odjezdy.

    - Sloučené linky (MERGED_LINES, např. 12 + 10, 65) mají jednu kartičku bez ohledu na cíl.
      Výchozí linka skupiny se u času neoznačuje, ostatní mají za časem své číslo.
    - U linek, kde část spojů na konečné pokračuje dál (72 z Kolejní přes Technologický park),
      je jedno, kam přesně pak vůz jede – rozlišujeme jen "jede dál" a "končí". Končící spoje
      jsou až na konci a nevýrazně (jen ať je vidět, že existují).
    """
    merged_of = {line: group for group in merged for line in group}
    continuing_lines = {d.line for d in departures if d.continues_to and d.line not in merged_of}
    # klíč: (nadpis kartičky, končící?) ; nadpis bez emoji, to se doplní z prvního odjezdu
    groups: dict[tuple[str, bool], list[Departure]] = defaultdict(list)
    for d in departures:
        group = merged_of.get(d.line)
        if group:
            groups[(" / ".join(group), False)].append(d)
        elif d.line in continuing_lines and d.continues_to:
            groups[(f"{d.line} ↪ jede dál", False)].append(d)
        elif d.line in continuing_lines:
            groups[(f"{d.line} → {d.headsign}", True)].append(d)
        else:
            groups[(f"{d.line} → {d.headsign}", False)].append(d)

    fields = []
    # nejdřív normální kartičky podle nejbližšího odjezdu, končící spoje až na konec
    for (title, ends), deps in sorted(groups.items(), key=lambda kv: (kv[0][1], kv[1][0].when)):
        group = merged_of.get(deps[0].line)
        if ends:
            rows = ["🛑 _končí, dál nejede_"] + [_time_row(d, bold=False) for d in deps[:2]]
        elif group:
            rows = [_time_row(d, tag=d.line if d.line != group[0] else None) for d in deps[:PER_CARD]]
        else:
            via = deps[0].last_stop if deps[0].continues_to else None
            rows = ([f"_přes {via}_"] if via else []) + [_time_row(d) for d in deps[:PER_CARD]]
        fields.append(render.Field(f"{deps[0].emoji} {title}", "\n".join(rows)))
    return fields[:MAX_CARDS]


def _board_embed(board: Board, departures: list[Departure], limit: int) -> discord.Embed:
    # Pozor: Discord slučuje embedy se stejnou URL do jednoho, proto unikátní kotva pro každou zastávku
    embed = discord.Embed(
        title=f"{board.emoji} {board.name}", url=f"{DEPARTURES_URL}#{board.key}", color=board.color
    )
    fields = _cards(departures)
    if fields:
        render.add_fields(embed, fields, limit)
    else:
        embed.description = "_V příští hodině odsud nic nejede._ 💤"
    if board.note:
        embed.set_footer(text=board.note)
    return embed


def _alerts_embed(alerts: list[alerts_mod.Alert], lines: set[str]) -> discord.Embed:
    embed = discord.Embed(title="⚠️ Výluky na těchto linkách", url=alerts_mod.LOCKOUTS_URL, color=0xF59F00)
    for a in alerts[:MAX_ALERTS]:
        affected = ", ".join(l for l in a.lines if l in lines)
        text = a.text if len(a.text) <= 300 else a.text[:300].rsplit(" ", 1)[0] + "…"
        embed.add_field(name=f"{affected} · {a.title}"[:256], value=text or "—", inline=False)
    if len(alerts) > MAX_ALERTS:
        embed.set_footer(text=f"…a dalších {len(alerts) - MAX_ALERTS} na idsjmk.cz")
    return embed


async def build_message(
    transit: Transit, group: str, force: bool = False
) -> tuple[str, list[discord.Embed], discord.ui.View]:
    timetable: Timetable = await transit.timetable()
    now = datetime.now(TZ)
    boards = [BOARDS[k] for k in GROUPS[group]]
    per_board = [
        timetable.departures(timetable.stops_named(b.name), now, route_types=b.route_types) for b in boards
    ]

    try:
        all_alerts = await transit.alerts(force=force)
        alerts_error = False
    except Exception:
        log.exception("Načtení výluk selhalo")
        all_alerts, alerts_error = [], True

    lines = {d.line for deps in per_board for d in deps}
    relevant = alerts_mod.for_lines(all_alerts, lines)

    limit = render.per_embed_limit(len(boards) + (1 if relevant else 0))
    embeds = [_board_embed(b, deps, limit) for b, deps in zip(boards, per_board)]
    if relevant:
        embeds.append(_alerts_embed(relevant, lines))

    info = f"🗓️ Podle jízdního řádu IDS JMK (bez zpoždění) · stav k <t:{int(now.timestamp())}:t>"
    if alerts_error:
        info += " · ⚠️ výluky se nepodařilo načíst"
    elif not relevant:
        info += " · ✅ bez výluk"
    content = f"### 🚏 Odjezdy MHD – {render.czech_date(now.date())}\n{info}"
    return content, embeds, build_view(group)


def _transit(client: discord.Client) -> Transit:
    cog = client.get_cog("Mhd")  # type: ignore[attr-defined]
    return cog.transit


class MhdButton(discord.ui.DynamicItem[discord.ui.Button], template=r"mhd:(?P<group>[a-z_]+):(?P<slot>[gr])"):
    """slot: g = přepnutí zastávky, r = obnovit"""

    def __init__(self, group: str, slot: str, **button_kwargs) -> None:
        super().__init__(discord.ui.Button(custom_id=f"mhd:{group}:{slot}", **button_kwargs))
        self.group = group
        self.slot = slot

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> MhdButton:
        return cls(match["group"], match["slot"])

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.group not in GROUPS:
            await interaction.response.send_message("Tohle tlačítko už je zastaralé.", ephemeral=True)
            return
        await interaction.response.defer()
        content, embeds, view = await build_message(
            _transit(interaction.client), self.group, force=self.slot == "r"
        )
        await interaction.edit_original_response(content=content, embeds=embeds, view=view)


def build_view(group: str) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for key, label in GROUP_LABELS.items():
        current = key == group
        view.add_item(
            MhdButton(
                key,
                "g",
                label=label,
                style=discord.ButtonStyle.primary if current else discord.ButtonStyle.secondary,
                disabled=current,
                row=0,
            )
        )
    view.add_item(MhdButton(group, "r", label="Obnovit", emoji="🔄", style=discord.ButtonStyle.secondary, row=1))
    view.add_item(discord.ui.Button(label="Online odjezdy IDS JMK", url=DEPARTURES_URL, row=1))
    return view


class Mhd(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.transit = Transit(bot.fetcher)

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(MhdButton)
        self.refresh_timetable.start()

    async def cog_unload(self) -> None:
        self.refresh_timetable.cancel()
        self.bot.remove_dynamic_items(MhdButton)

    @tasks.loop(hours=3)
    async def refresh_timetable(self) -> None:
        """Načte jízdní řád hned po startu a pak ho průběžně obnovuje (stáhne, jen když je starý)."""
        try:
            await self.transit.refresh()
        except Exception:
            log.exception("Obnova jízdního řádu selhala")

    @app_commands.command(name="mhd", description="Nejbližší odjezdy MHD z Technologického parku a Kolejní")
    @app_commands.describe(zastavka="Kterou zastávku ukázat (výchozí: obě)")
    @app_commands.choices(zastavka=[app_commands.Choice(name=v, value=k) for k, v in GROUP_LABELS.items()])
    async def mhd(self, interaction: discord.Interaction, zastavka: str = "vse") -> None:
        await interaction.response.defer(thinking=True)
        content, embeds, view = await build_message(self.transit, zastavka)
        await interaction.followup.send(content=content, embeds=embeds, view=view)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Mhd(bot))
