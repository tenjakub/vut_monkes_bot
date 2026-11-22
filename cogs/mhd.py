"""/mhd – odjezdy MHD z vybraných zastávek podle jízdního řádu IDS JMK + aktuální výluky."""

from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from collections.abc import Callable
from dataclasses import dataclass
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
    HOME_NIGHT_LINES,
    HOME_ORIGINS,
    HOME_ROUTE_TYPES,
    HOMES,
    Board,
    Transit,
    area_of,
)
from utils import loading, render
from utils.interactions import STALE, reported

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


def _home_connections(timetable: Timetable, home: str, now: datetime) -> list[Connection]:
    """Všechny spoje z centra k jedněm kolejím do konce noci (spoj přes víc výchozích zastávek je tu víckrát)."""
    _, stops = HOMES[home]
    origins = [sid for name in HOME_ORIGINS for sid in timetable.stops_named(name)]
    dests = [sid for name in stops for sid in timetable.stops_named(name)]
    return [
        c for c in timetable.connections(origins, dests, now, _night_end(now))
        # autobusy a jiné noční linky nechceme (viz HOME_ROUTE_TYPES, HOME_NIGHT_LINES)
        if c.route_type in HOME_ROUTE_TYPES or c.line in HOME_NIGHT_LINES
    ]


def _by_trip(connections: list[Connection]) -> dict[tuple[str, datetime], list[Connection]]:
    """Seskupí spoje podle konkrétní jízdy (trip_id + příjezd, protože trip_id se opakuje každý den)."""
    trips: dict[tuple[str, datetime], list[Connection]] = defaultdict(list)
    for c in connections:
        trips[(c.trip_id, c.arrival)].append(c)
    return trips


def home_trips(timetable: Timetable, home: str, now: datetime) -> list[Connection]:
    """Spoje z centra domů do konce noci; když spoj projede víc výchozími zastávkami, bere se ta
    první podle HOME_ORIGINS (Česká před Hlavním nádražím)."""
    return _preferred(_home_connections(timetable, home, now))


def _preferred(connections: list[Connection]) -> list[Connection]:
    preference = {name: i for i, name in enumerate(HOME_ORIGINS)}
    best = [min(group, key=lambda c: preference.get(c.origin, 99)) for group in _by_trip(connections).values()]
    return sorted(best, key=lambda c: (c.departure, c.line))


def origin_offsets(connections: list[Connection]) -> dict[str, int]:
    """O kolik minut dřív jede linka z druhé výchozí zastávky (Hlavní nádraží) než z hlavní (Česká).
    Bere se nejčastější rozdíl z jízdního řádu (u 12 bývá 6 min, občas 5)."""
    main, other = HOME_ORIGINS[0], HOME_ORIGINS[1]
    diffs: dict[str, Counter[int]] = defaultdict(Counter)
    for group in _by_trip(connections).values():
        at = {c.origin: c for c in group}
        if main in at and other in at:
            minutes = round((at[main].departure - at[other].departure).total_seconds() / 60)
            diffs[at[main].line][minutes] += 1
    return {line: counter.most_common(1)[0][0] for line, counter in diffs.items()}


@dataclass(frozen=True)
class HomeTrip:
    """Jeden spoj z centra a kdy dorazí ke kterým kolejím (jedna linka může jet k oběma)."""

    trip: Connection  # výchozí zastávka, odjezd, linka
    arrivals: tuple[tuple[str, datetime], ...]  # (koleje, příjezd), seřazeno podle příjezdu

    @property
    def night(self) -> bool:
        return self.trip.night


def all_home_trips(timetable: Timetable, now: datetime) -> tuple[list[HomeTrip], dict[str, int]]:
    """Spoje domů ke všem kolejím dohromady (stejný spoj jednou, s příjezdy ke všem kolejím)
    a o kolik minut dřív jednotlivé linky jedou z Hlavního nádraží."""
    merged: dict[tuple[str, datetime], tuple[Connection, list[tuple[str, datetime]]]] = {}
    offsets: dict[str, int] = {}
    for key, (label, _) in HOMES.items():
        connections = _home_connections(timetable, key, now)
        for c in _preferred(connections):
            merged.setdefault((c.trip_id, c.departure), (c, []))[1].append((label, c.arrival))
        offsets |= origin_offsets(connections)
    trips = [HomeTrip(c, tuple(sorted(a, key=lambda x: x[1]))) for c, a in merged.values()]
    return sorted(trips, key=lambda t: (t.trip.departure, t.trip.line)), offsets


def _arrivals(t: HomeTrip) -> str:
    return " · ".join(f"{label} {_hm(when)}" for label, when in t.arrivals)


def _departure(t: HomeTrip, bold: bool = False) -> str:
    """Odjezd + linka; výchozí zastávka jen když to není hlavní (Česká), ta je v záhlaví."""
    where = f" {t.trip.origin}" if t.trip.origin != HOME_ORIGINS[0] else ""
    time = f"**{_hm(t.trip.departure)}**" if bold else _hm(t.trip.departure)
    return f"{time}{where} · {t.trip.emoji} {t.trip.line}"


def _offsets_line(trips: list[HomeTrip], offsets: dict[str, int]) -> str:
    """'🚉 Časy jsou z České. Z Hlavního nádraží jede 🚋 12 o 6 min a 🚌 N99 o 3 min dřív.'"""
    shown: dict[str, str] = {}  # linka -> emoji, v pořadí podle prvního odjezdu
    for t in trips:
        if t.trip.line in offsets and offsets[t.trip.line] > 0:
            shown.setdefault(t.trip.line, t.trip.emoji)
    main, other = HOME_ORIGINS[0], HOME_ORIGINS[1]
    text = f"🚉 Časy jsou ze zastávky **{main}**."
    if shown:
        parts = [f"{emoji} {line} o {offsets[line]} min" for line, emoji in shown.items()]
        joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " a " + parts[-1]
        text += f" Ze zastávky {other} jede {joined} dřív."
    return text


def _home_embed(trips: list[HomeTrip], offsets: dict[str, int], now: datetime) -> discord.Embed:
    embed = discord.Embed(title="🌙 Domů na koleje", url=f"{DEPARTURES_URL}#domu", color=0x5F3DC4)
    lines = [_offsets_line(trips, offsets), ""]
    upcoming = [t for t in trips if t.trip.departure <= now + UPCOMING_WINDOW][:MAX_UPCOMING]
    if upcoming:
        lines.append("**Nejbližší spoje**")
        lines += [f"{_departure(t, bold=True)} → {_arrivals(t)}" for t in upcoming]
    else:
        lines.append("_V příštích dvou hodinách nic nejede._")
    # poslední denní spoj ke každým kolejím (k jedněm může jet poslední tramvaj dřív než k druhým)
    day = [t for t in trips if not t.night]
    lasts: list[HomeTrip] = []
    for label, _ in HOMES.values():
        last = next((t for t in reversed(day) if any(lb == label for lb, _ in t.arrivals)), None)
        if last is not None and last not in lasts:
            lasts.append(last)
    lasts.sort(key=lambda t: t.trip.departure)
    if lasts:
        items = [f"{_departure(t)} ({_arrivals(t)})" for t in lasts]
        if len(items) == 1:
            lines.append(f"\n🌙 **Poslední denní spoj:** {items[0]}")
        else:
            lines.append("\n🌙 **Poslední denní spoje:**\n" + "\n".join(items))
    elif any(t.night for t in trips):
        lines.append("\n🌙 Denní spoje už dnes nejedou.")
    # noční spoje po posledním denním; když denní už nejedou, jsou noční rovnou v "Nejbližších"
    nights = [t.trip for t in trips if t.night and day and t.trip.departure > day[-1].trip.departure][:MAX_NIGHT]
    if nights:
        items = [
            f"{_hm(c.departure)} {c.line}" + (f" ({c.origin})" if c.origin != HOME_ORIGINS[0] else "") for c in nights
        ]
        lines.append("🦉 **Noční:** " + " · ".join(items))
    embed.description = "\n".join(lines)
    return embed


async def build_home_message(transit: Transit) -> tuple[str, list[discord.Embed], discord.ui.View]:
    timetable = await transit.timetable()
    now = datetime.now(TZ)
    trips, offsets = all_home_trips(timetable, now)
    embeds = [_home_embed(trips, offsets, now)]
    content = (
        f"### 🌙 Domů z centra – {render.czech_date(now.date())}\n"
        f"-# Podle jízdního řádu (bez zpoždění) · stav k <t:{int(now.timestamp())}:t>"
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

    @reported
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

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        if self.group not in GROUPS:
            await interaction.response.send_message(STALE, ephemeral=True)
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
            loading.expect(self.bot, "jízdní řád MHD")
            loading.expect(self.bot, "výluky MHD")

    async def cog_unload(self) -> None:
        self.refresh_timetable.cancel()
        self.refresh_alerts.cancel()
        self.bot.remove_dynamic_items(MhdButton, DomuButton)

    @tasks.loop(minutes=ALERTS_REFRESH_MINUTES)
    async def refresh_alerts(self) -> None:
        """Výluky z realtime feedu na pozadí, ať /mhd nečeká na stažení."""
        try:
            async with loading.track(self.bot, "výluky MHD"):
                await self.transit.alerts(force=True)
        except Exception:
            log.exception("Obnova výluk selhala")

    @tasks.loop(hours=3)
    async def refresh_timetable(self) -> None:
        """Načte jízdní řád hned po startu a pak ho průběžně obnovuje (stáhne, jen když je starý)."""
        try:
            async with loading.track(self.bot, "jízdní řád MHD"):
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
