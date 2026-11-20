"""/mhd – odjezdy MHD z vybraných zastávek podle jízdního řádu IDS JMK + aktuální výluky."""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from transit import alerts as alerts_mod
from transit.gtfs import TZ, Connection, Departure, Timetable
from transit.service import (
    ALERTS_REFRESH_MINUTES,
    AREAS,
    BOARDS,
    GROUPS,
    HOME_ORIGINS,
    HOMES,
    Board,
    Transit,
    area_of,
)
from utils import render

log = logging.getLogger(__name__)

DEPARTURES_URL = "https://www.idsjmk.cz/departures/index"
PER_CARD = 4  # kolik nejbližších odjezdů ukázat v jedné kartičce
MAX_CARDS = 12
MAX_ALERTS = 3

UsualHeadsign = Callable[[str, str], "str | None"]  # (stop_id, linka) -> obvyklá konečná



def _time_row(d: Departure, bold: bool = True, tag: str | None = None) -> str:
    time = f"**{d.when:%H:%M}**" if bold else f"{d.when:%H:%M}"
    row = f"{time} · <t:{int(d.when.timestamp())}:R>"
    return f"{row} · `{tag}`" if tag else row


def _most_common(values) -> str:
    return Counter(values).most_common(1)[0][0]


def _merge_cards(
    departures: list[Departure], board: Board, usual: UsualHeadsign | None = None
) -> list[render.Field]:
    """Jedna kartička na směr (nástupiště) pro všechny linky: "🚋 Tram → Centrum",
    u každého času číslo linky."""
    by_platform: dict[str, list[Departure]] = defaultdict(list)
    for d in departures:
        by_platform[d.stop_id].append(d)
    labels = dict(board.directions)
    cards = []
    for stop_id, deps in sorted(by_platform.items(), key=lambda kv: kv[1][0].when):
        line = _most_common(d.line for d in deps)
        direction = labels.get(stop_id) or (usual(stop_id, line) if usual else None) or _most_common(
            d.headsign for d in deps
        )
        rows = [_time_row(d, tag=d.line) for d in deps[:PER_CARD]]
        cards.append(render.Field(f"{deps[0].emoji} {board.vehicle} → {direction}", "\n".join(rows)))
    return cards


def _line_key(line: str) -> tuple[int, int, str]:
    """Řazení linek: 30, 44, 67, 72, 84, … a pak noční/ostatní (N93, x72)."""
    return (0, int(line), "") if line.isdigit() else (1, 0, line)


def _line_cards(departures: list[Departure], usual: UsualHeadsign | None = None) -> list[render.Field]:
    """Kartička pro každou linku a směr, seřazené podle čísla linky (stálé pořadí v mřížce).

    V nadpisu je obvyklá konečná linky z toho nástupiště (podle celého jízdního řádu),
    jiné konečné jsou jen značka za časem.
    """
    groups: dict[tuple[str, str], list[Departure]] = defaultdict(list)
    for d in departures:
        groups[(d.line, d.stop_id)].append(d)
    cards = []
    for (line, stop_id), deps in sorted(groups.items(), key=lambda kv: (_line_key(kv[0][0]), kv[0][1])):
        main = (usual(stop_id, line) if usual else None) or _most_common(d.headsign for d in deps)
        rows = [_time_row(d, tag=d.headsign if d.headsign != main else None) for d in deps[:PER_CARD]]
        cards.append(render.Field(f"{deps[0].emoji} {line} → {main}", "\n".join(rows)))
    return cards


def _auto_cards(departures: list[Departure], board: Board) -> list[render.Field]:
    """Kartičky podle linky a cíle.

    - `board.merged_lines` (65 na Kolejní) mají jednu kartičku bez ohledu na cíl.
    - U linek, kde část spojů na konečné pokračuje dál (72 z Kolejní přes Technologický park),
      je jedno, kam přesně pak vůz jede – rozlišujeme jen "jede dál" a "končí". Pokud má linka
      v `board.continuing` popisek směru, kartička je "72 → Semilasso" a je vždy první. Končící
      spoje jsou až na konci a nevýrazně (jen ať je vidět, že existují).
    """
    directions = dict(board.continuing)
    continuing_lines = {d.line for d in departures if d.continues_to and d.line not in board.merged_lines}
    # klíč: (nadpis bez emoji, připnutá?, končící?)
    groups: dict[tuple[str, bool, bool], list[Departure]] = defaultdict(list)
    for d in departures:
        if d.line in board.merged_lines:
            groups[(d.line, False, False)].append(d)
        elif d.line in continuing_lines and d.continues_to:
            if d.line in directions:
                groups[(f"{d.line} → {directions[d.line]}", True, False)].append(d)
            else:
                groups[(f"{d.line} ↪ jede dál", False, False)].append(d)
        elif d.line in continuing_lines:
            groups[(f"{d.line} → {d.headsign}", False, True)].append(d)
        else:
            groups[(f"{d.line} → {d.headsign}", False, False)].append(d)

    cards = []
    # připnuté první, končící poslední, jinak podle nejbližšího odjezdu
    for (title, pinned, ends), deps in sorted(groups.items(), key=lambda kv: (kv[0][2], not kv[0][1], kv[1][0].when)):
        if ends:
            rows = ["🛑 _končí, dál nejede_"] + [_time_row(d, bold=False) for d in deps[:2]]
        else:
            show_via = deps[0].continues_to and not pinned
            rows = ([f"_přes {deps[0].last_stop}_"] if show_via else []) + [_time_row(d) for d in deps[:PER_CARD]]
        cards.append(render.Field(f"{deps[0].emoji} {title}", "\n".join(rows)))
    return cards


def _cards(
    departures: list[Departure], board: Board, usual: UsualHeadsign | None = None
) -> list[render.Field]:
    if board.layout == "merge":
        cards = _merge_cards(departures, board, usual)
    elif board.layout == "lines":
        cards = _line_cards(departures, usual)
    else:
        cards = _auto_cards(departures, board)
    return cards[:MAX_CARDS]


def _board_embed(
    board: Board, departures: list[Departure], limit: int, usual: UsualHeadsign | None = None
) -> discord.Embed:
    # Pozor: Discord slučuje embedy se stejnou URL do jednoho, proto unikátní kotva pro každou zastávku
    embed = discord.Embed(
        title=f"{board.emoji} {board.label}", url=f"{DEPARTURES_URL}#{board.key}", color=board.color
    )
    fields = _cards(departures, board, usual)
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
        embed.set_footer(text=f"+ další výluky ({len(alerts) - MAX_ALERTS}) na idsjmk.cz")
    return embed


async def build_message(
    transit: Transit, group: str, force: bool = False
) -> tuple[str, list[discord.Embed], discord.ui.View]:
    timetable: Timetable = await transit.timetable()
    now = datetime.now(TZ)
    boards = [BOARDS[k] for k in GROUPS[group]]
    per_board = [
        timetable.departures(b.platforms or timetable.stops_named(b.name), now, route_types=b.route_types)
        for b in boards
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
    embeds = [_board_embed(b, deps, limit, timetable.usual_headsign) for b, deps in zip(boards, per_board)]
    if relevant:
        embeds.append(_alerts_embed(relevant, lines))

    info = f"🗓️ Podle jízdního řádu IDS JMK (bez zpoždění) · stav k <t:{int(now.timestamp())}:t>"
    if alerts_error:
        info += " · ⚠️ výluky se nepodařilo načíst"
    elif not relevant:
        info += " · ✅ bez výluk"
    area_label = AREAS[area_of(group)][0]
    content = f"### 🚏 MHD {area_label} – {render.czech_date(now.date())}\n{info}"
    return content, embeds, build_view(group)


# --- /domu: spoje z centra ke kolejím -------------------------------------------------------------

UPCOMING_WINDOW = timedelta(hours=2)
MAX_UPCOMING = 6
MAX_NIGHT = 6


def _hm(d: datetime) -> str:
    return f"{d.hour}:{d.minute:02d}"


def _night_end(now: datetime) -> datetime:
    """Konec "dnešní noci" = nejbližší 4:00 ráno (do té doby hledáme poslední a noční spoje)."""
    four = now.replace(hour=4, minute=0, second=0, microsecond=0)
    return four if now < four else four + timedelta(days=1)


def home_trips(timetable: Timetable, home: str, now: datetime) -> list[Connection]:
    """Spoje z centra domů do konce noci; když spoj projede víc výchozími zastávkami, bere se ta
    první podle HOME_ORIGINS (Česká před Hlavním nádražím)."""
    _, stops = HOMES[home]
    origins = [sid for name in HOME_ORIGINS for sid in timetable.stops_named(name)]
    dests = [sid for name in stops for sid in timetable.stops_named(name)]
    preference = {name: i for i, name in enumerate(HOME_ORIGINS)}
    best: dict[tuple[str, datetime], Connection] = {}
    for c in timetable.connections(origins, dests, now, _night_end(now)):
        key = (c.trip_id, c.arrival)
        if key not in best or preference.get(c.origin, 99) < preference.get(best[key].origin, 99):
            best[key] = c
    return sorted(best.values(), key=lambda c: (c.departure, c.line))


def _home_embed(home: str, trips: list[Connection], now: datetime) -> discord.Embed:
    label, _ = HOMES[home]
    embed = discord.Embed(title=f"🌙 Domů na {label}", url=f"{DEPARTURES_URL}#domu-{home}", color=0x5F3DC4)
    lines = []
    upcoming = [c for c in trips if c.departure <= now + UPCOMING_WINDOW][:MAX_UPCOMING]
    if upcoming:
        lines.append("**Nejbližší spoje**")
        lines += [
            f"**{_hm(c.departure)}** {c.origin} · {c.emoji} {c.line} → {c.destination} {_hm(c.arrival)}" for c in upcoming
        ]
    else:
        lines.append("_V příštích dvou hodinách nic nejede._")
    day = [c for c in trips if not c.night]
    if day:
        last = day[-1]
        lines.append(
            f"\n🌙 **Poslední denní spoj:** {_hm(last.departure)} {last.origin} · {last.emoji} {last.line} "
            f"(doma {_hm(last.arrival)})"
        )
    elif any(c.night for c in trips):
        lines.append("\n🌙 Denní spoje už dnes nejedou.")
    # noční spoje po posledním denním; když denní už nejedou, jsou noční rovnou v "Nejbližších"
    nights = [c for c in trips if c.night and day and c.departure > day[-1].departure][:MAX_NIGHT]
    if nights:
        if len({c.origin for c in nights}) == 1:  # všechny ze stejné zastávky -> stačí ji napsat jednou
            items, where = [f"{_hm(c.departure)} {c.line}" for c in nights], f" (z: {nights[0].origin})"
        else:
            items, where = [f"{_hm(c.departure)} {c.line} {c.origin}" for c in nights], ""
        lines.append("🦉 **Noční:** " + " · ".join(items) + where)
    embed.description = "\n".join(lines)
    return embed


async def build_home_message(transit: Transit) -> tuple[str, list[discord.Embed], discord.ui.View]:
    timetable = await transit.timetable()
    now = datetime.now(TZ)
    embeds = [_home_embed(key, home_trips(timetable, key, now), now) for key in HOMES]
    origins = ", ".join(HOME_ORIGINS[:-1]) + " nebo " + HOME_ORIGINS[-1]
    content = (
        f"### 🌙 Domů z centra – {render.czech_date(now.date())}\n"
        f"-# Z: {origins} · podle jízdního řádu (bez zpoždění) · stav k <t:{int(now.timestamp())}:t>"
    )
    return content, embeds, build_home_view()


class DomuButton(discord.ui.DynamicItem[discord.ui.Button], template=r"domu:r"):
    def __init__(self) -> None:
        super().__init__(
            discord.ui.Button(custom_id="domu:r", label="Obnovit", emoji="🔄", style=discord.ButtonStyle.secondary)
        )

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> DomuButton:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        content, embeds, view = await build_home_message(_transit(interaction.client))
        await interaction.edit_original_response(content=content, embeds=embeds, view=view)


def build_home_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(DomuButton())
    view.add_item(discord.ui.Button(label="IDS JMK", url=DEPARTURES_URL))
    return view


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
    """1. řada: oblasti (PPV / Purkyně), 2. řada: zastávky oblasti, obnovit, odkaz."""
    view = discord.ui.View(timeout=None)
    area = area_of(group)

    def button(key: str, label: str, row: int) -> MhdButton:
        current = key == group
        return MhdButton(
            key,
            "g",
            label=label,
            style=discord.ButtonStyle.primary if current else discord.ButtonStyle.secondary,
            disabled=current,
            row=row,
        )

    for key, (label, _) in AREAS.items():
        view.add_item(button(key, label, 0))
    for key in AREAS[area][1]:
        view.add_item(button(key, BOARDS[key].label, 1))
    view.add_item(MhdButton(group, "r", label="Obnovit", emoji="🔄", style=discord.ButtonStyle.secondary, row=1))
    view.add_item(discord.ui.Button(label="IDS JMK", url=DEPARTURES_URL, row=1))
    return view


class Mhd(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.transit = Transit(bot.fetcher)

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(MhdButton, DomuButton)
        if getattr(self.bot, "background_refresh", True):
            self.refresh_timetable.start()
            self.refresh_alerts.start()

    async def cog_unload(self) -> None:
        self.refresh_timetable.cancel()
        self.refresh_alerts.cancel()
        self.bot.remove_dynamic_items(MhdButton, DomuButton)

    @tasks.loop(minutes=ALERTS_REFRESH_MINUTES)
    async def refresh_alerts(self) -> None:
        """Výluky z realtime feedu na pozadí, ať /mhd nečeká na stažení."""
        try:
            await self.transit.alerts(force=True)
        except Exception:
            log.exception("Obnova výluk selhala")

    @tasks.loop(hours=3)
    async def refresh_timetable(self) -> None:
        """Načte jízdní řád hned po startu a pak ho průběžně obnovuje (stáhne, jen když je starý)."""
        try:
            await self.transit.refresh()
        except Exception:
            log.exception("Obnova jízdního řádu selhala")

    async def _send(self, interaction: discord.Interaction, group: str) -> None:
        await interaction.response.defer(thinking=True)
        content, embeds, view = await build_message(self.transit, group)
        await interaction.followup.send(content=content, embeds=embeds, view=view)

    @app_commands.command(name="mhd", description="Odjezdy MHD u PPV: Technologický park (tramvaje) a Kolejní")
    @app_commands.describe(zastavka="Kterou zastávku ukázat (výchozí: obě)")
    @app_commands.choices(
        zastavka=[app_commands.Choice(name="Obě zastávky", value="vse")]
        + [app_commands.Choice(name=BOARDS[k].label, value=k) for k in AREAS["vse"][1]]
    )
    async def mhd(self, interaction: discord.Interaction, zastavka: str = "vse") -> None:
        await self._send(interaction, zastavka)

    @app_commands.command(name="domu", description="🌙 Jak se dostat z centra na koleje – nejbližší, poslední denní a noční spoje")
    async def domu(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True)
        content, embeds, view = await build_home_message(self.transit)
        await interaction.followup.send(content=content, embeds=embeds, view=view)

    @app_commands.command(name="mhd-purkyne", description="Odjezdy MHD u kolejí Purkyňova: Červinkova (tramvaje) a Skácelova (busy)")
    async def mhd_purkyne(self, interaction: discord.Interaction) -> None:
        await self._send(interaction, "purkyne")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Mhd(bot))
