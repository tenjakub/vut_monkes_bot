"""/na-pivo a /na-pivo-termin – domluva na pivo.

- /na-pivo: pozvánka na konkrétní den (dnes). Ve výběrech se nastaví, v kolik a kam (kdokoliv to může
  změnit), a každý klikne ✅ Jdu / 📅 Jindy / ❌ Nejdu.
- /na-pivo-termin: hledání společného dne v příštích dvou týdnech. Každý klikne na dny, kdy může,
  a v okně vybere, od kolika. Nahoře je vidět nejlepší termín a tlačítkem se na něj dá rovnou svolat.

Jako u /obed je celý stav jen v embedu zprávy (kdo, kdy, kam), takže přežije restart bota.
Datum založení je v `embed.timestamp`, z něj se dopočítá rok a dny hlasování.
"""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

import discord
from discord import app_commands
from discord.ext import commands

from lunch import service
from pubs import planning, venues
from utils import render
from weather import openmeteo

COLOR = 0xE8A317  # barva piva
TIMES = [f"{h}:{m:02d}" for h in range(14, 23) for m in (0, 30)][:-1]  # 14:00 … 22:00 pro /na-pivo
FROM_TIMES = [f"{h}:00" for h in range(14, 22)]  # "můžu od" pro /na-pivo-termin
STALE = "Tohle tlačítko už je zastaralé."

# odpověď -> (emoji, nadpis kartičky, popisek tlačítka, styl tlačítka)
ANSWERS: dict[str, tuple[str, str, str, discord.ButtonStyle]] = {
    "jdu": ("✅", "Jdou", "Jdu", discord.ButtonStyle.success),
    "jindy": ("📅", "Šli by jindy", "Jindy", discord.ButtonStyle.primary),
    "nejdu": ("❌", "Nejdou", "Nejdu", discord.ButtonStyle.danger),
}

_COUNT_RE = re.compile(r"\s*\(\d+\)$")
_USER_RE = re.compile(r"<@(\d+)>")
_CREATOR_RE = re.compile(r"Svolává <@(\d+)>")
_TIME_RE = re.compile(r"🕐 \*\*Kdy:\*\* (\d{1,2}:\d{2})")
_PLACE_RE = re.compile(r"📍 \*\*Kam:\*\* \S+ \*\*(.+?)\*\*")
_DATE_RE = re.compile(r"(\d{1,2})\. (\d{1,2})\.$")
_VOTE_RE = re.compile(r"<@(\d+)> · (?:od (\d{1,2}:\d{2})|kdykoliv)")
_locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)  # zpráva -> zámek (dvě kliknutí naráz)


def forecast(client) -> openmeteo.Forecast | None:
    """Předpověď z cache, kterou na pozadí obnovuje /pocasi. Nic se kvůli ní nestahuje; bez ní se počasí jen neukáže."""
    fetcher = getattr(client, "fetcher", None)
    text = fetcher.peek(openmeteo.URL) if fetcher else None
    try:
        return openmeteo.parse(text) if text else None
    except (ValueError, KeyError, TypeError):
        return None


def _weather_line(weather: openmeteo.Forecast | None, day: date, time: str | None) -> str | None:
    """'-# 🌧️ déšť · 6 °C · 💧 60 % (od 19:00)' – počasí v den a čas piva (bez času večer od 18:00)."""
    if weather is None:
        return None
    hour = int(time.split(":")[0]) if time else openmeteo.EVENING_HOUR
    o = openmeteo.outlook(weather, day, hour)
    return f"-# {o.line()} (od {hour}:00)" if o else None


def _footer(embed: discord.Embed, text: str, weather_shown: bool) -> None:
    embed.set_footer(text=text + (" · počasí: Open-Meteo.com" if weather_shown else ""))


def _now() -> datetime:
    return datetime.now(service.TZ)


def _created(embed: discord.Embed) -> datetime | None:
    return embed.timestamp.astimezone(service.TZ) if embed.timestamp else None


def _creator(embed: discord.Embed) -> str:
    m = _CREATOR_RE.search(embed.description or "")
    return m.group(1) if m else ""


# --- kam -----------------------------------------------------------------------------------------


def place_lines(key: str | None) -> list[str]:
    """Řádek „📍 Kam“ do popisu embedu. U oblasti pod ním nevýrazně podniky, které do ní patří."""
    if key in venues.PUBS:
        pub = venues.PUBS[key]
        parts = [f"{pub.emoji} **{pub.name}**", pub.address, f"[🗺️ mapa]({pub.map})"]
        lines = ["📍 **Kam:** " + " · ".join(p for p in parts if p)]
        if pub.beer_text:
            lines.append(f"-# {pub.beer_text}")
        return lines
    if key in venues.AREAS:
        area = venues.AREAS[key]
        lines = [f"📍 **Kam:** {area.emoji} **{area.label}** – {area.note}"]
        if pubs := venues.pubs_in(key):
            lines.append("-# " + " · ".join(f"[{p.name}]({p.map})" for p in pubs))
        return lines
    return ["📍 **Kam:** _ještě se neví – vyber níž_"]


def read_place(embed: discord.Embed) -> str | None:
    m = _PLACE_RE.search(embed.description or "")
    return venues.by_name(m.group(1)) if m else None


def place_options(current: str | None) -> list[discord.SelectOption]:
    """Nahoře pohromadě obecné možnosti (kamkoliv, oblasti), pod nimi podniky seřazené po oblastech.
    Discord unese ve výběru nejvýš 25 možností."""
    options = []
    for area in venues.AREAS.values():
        names = ", ".join(p.name for p in venues.pubs_in(area.key))
        options.append(discord.SelectOption(
            label=f"{area.label} – {area.hint}", value=area.key, emoji=area.emoji,
            description=names[:100] or None, default=current == area.key,
        ))
    for area in venues.AREAS.values():
        for pub in venues.pubs_in(area.key):
            options.append(discord.SelectOption(
                label=pub.name, value=pub.key, emoji=pub.emoji,
                description=" · ".join(p for p in (area.label, pub.address) if p)[:100], default=current == pub.key,
            ))
    return options[:25]


MAP_SMALL_AREA = 3  # oblast s víc podniky se v „Kde co je“ rozloží do tří sloupců přes celou šířku


def _map_line(p: venues.Pub) -> str:
    """Podnik v „Kde co je“: odkaz na mapu, pod ním nevýrazně adresa a (když je zapnutá) cena piva."""
    small = [x for x in (p.address, p.beer_text) if x]
    return f"{p.emoji} [{p.name}]({p.map})" + "".join(f"\n-# {x}" for x in small)


def map_embed() -> discord.Embed:
    """🗺️ Kde co je: všechny podniky po oblastech s odkazem na mapu.

    Malé oblasti jsou kartičky vedle sebe, velká (centrum) má vlastní řadu rozdělenou do tří sloupců
    (nadpis jen nad prvním), aby využila šířku. Na mobilu jdou sloupce pod sebe, proto se plní shora dolů.
    """
    embed = discord.Embed(title="🗺️ Kde co je", color=COLOR)
    fields: list[render.Field] = []
    areas = [(a, venues.pubs_in(a.key)) for a in venues.AREAS.values()]
    areas = [(a, pubs) for a, pubs in areas if pubs]
    # malé oblasti napřed, ať se poskládají do společné řady
    for area, pubs in sorted(areas, key=lambda ap: len(ap[1]) > MAP_SMALL_AREA):
        lines = [_map_line(p) for p in pubs]
        if len(pubs) <= MAP_SMALL_AREA:
            fields.append(render.Field(f"{area.emoji} {area.label}", "\n".join(lines)))
            continue
        while len(fields) % render.GRID_COLUMNS:  # velká oblast začíná na novém řádku
            fields.append(render.Field(render.BLANK, render.BLANK))
        cols = render.GRID_COLUMNS
        size, extra = divmod(len(lines), cols)
        start = 0
        for i in range(cols):
            end = start + size + (i < extra)
            name = f"{area.emoji} {area.label}" if i == 0 else render.BLANK
            fields.append(render.Field(name, "\n".join(lines[start:end]) or render.BLANK))
            start = end
    render.add_fields(embed, fields, 5000)
    return embed


# --- /na-pivo: pozvánka na konkrétní den -----------------------------------------------------------


@dataclass
class Meetup:
    day: date
    created: datetime
    creator: str
    time: str | None = None  # "19:00"
    place: str | None = None  # klíč oblasti nebo podniku
    answers: dict[int, str] = field(default_factory=dict)  # user -> klíč z ANSWERS

    def apply(self, user: int, answer: str) -> None:
        """Druhé kliknutí na stejnou odpověď tě odhlásí."""
        if self.answers.get(user) == answer:
            del self.answers[user]
        else:
            self.answers.pop(user, None)  # na konec, ať je pořadí podle posledního kliknutí
            self.answers[user] = answer

    def count(self, answer: str) -> int:
        return sum(a == answer for a in self.answers.values())


def meetup_embed(m: Meetup, weather: openmeteo.Forecast | None = None) -> discord.Embed:
    lines = [f"Svolává <@{m.creator}>"] if m.creator else []
    lines.append(f"🕐 **Kdy:** {m.time}" if m.time else "🕐 **Kdy:** _ještě se neví – vyber níž_")
    if w := _weather_line(weather, m.day, m.time):
        lines.append(w)
    lines += place_lines(m.place)
    lines.append("-# Klikni, jestli jdeš. Kdy a kam může upravit kdokoliv ve výběru pod zprávou.")
    embed = discord.Embed(
        title=f"🍺 Na pivo – {render.czech_date(m.day)}", description="\n".join(lines),
        color=COLOR, timestamp=m.created,
    )
    _footer(embed, "Svoláno", w is not None)
    fields = []
    for key, (icon, title, _, _) in ANSWERS.items():
        people = [f"<@{u}>" for u, a in m.answers.items() if a == key]
        fields.append(render.Field(f"{icon} {title} ({len(people)})", "\n".join(people) or "–"))
    render.add_fields(embed, fields, 5000)
    return embed


def read_meetup(embed: discord.Embed | None) -> Meetup | None:
    if embed is None or not (created := _created(embed)):
        return None
    m = _DATE_RE.search(embed.title or "")
    day = planning.resolve_date(int(m.group(1)), int(m.group(2)), created.date()) if m else None
    if day is None:
        return None
    time = _TIME_RE.search(embed.description or "")
    meetup = Meetup(day, created, _creator(embed), time.group(1) if time else None, read_place(embed))
    by_title = {f"{icon} {title}": key for key, (icon, title, _, _) in ANSWERS.items()}
    for f in embed.fields:
        answer = by_title.get(_COUNT_RE.sub("", f.name or ""))
        if answer:
            for user in _USER_RE.findall(f.value or ""):
                meetup.answers[int(user)] = answer
    return meetup


def meetup_view(m: Meetup) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(TimeSelect(m.time))
    view.add_item(PlaceSelect("napivo", m.place, row=1))
    for key, (icon, _, label, style) in ANSWERS.items():
        n = m.count(key)
        view.add_item(AnswerButton(key, label=f"{label} · {n}" if n else label, emoji=icon, style=style, row=2))
    view.add_item(MapButton(row=3))
    view.add_item(PlanNewButton(row=3))
    return view


# --- /na-pivo-termin: hledání společného dne -------------------------------------------------------


@dataclass
class Plan:
    created: datetime
    creator: str
    place: str | None = None
    votes: planning.Votes = field(default_factory=dict)

    @property
    def days(self) -> list[date]:
        return planning.plan_days(self.created.date())

    def vote(self, user: int, day: date, choice: str) -> None:
        """choice: "x" = nemůžu (zruší den), "any" = kdykoliv, jinak "HH:MM" = můžu od."""
        mine = self.votes.setdefault(user, {})
        if choice == "x":
            mine.pop(day, None)
        else:
            mine[day] = None if choice == "any" else choice
        if not mine:
            del self.votes[user]


def _vote_text(time: str | None) -> str:
    return f"od {time}" if time else "kdykoliv"


def plan_embed(p: Plan, today: date, weather: openmeteo.Forecast | None = None) -> discord.Embed:
    days = p.days
    best = planning.best_day(p.votes, today)
    lines = [f"Svolává <@{p.creator}>"] if p.creator else []
    lines += place_lines(p.place)
    if best:
        people = "člověk" if len(best.users) == 1 else ("lidi" if len(best.users) < 5 else "lidí")
        lines.append(f"🏆 **Zatím nejlíp:** {render.czech_date(best.day)} {_vote_text(best.time)} · "
                     f"{len(best.users)} {people}")
        if w := _weather_line(weather, best.day, best.time):
            lines.append(w)
    else:
        lines.append("\n_Zatím nikdo…_ 🦗")
    lines.append("-# Klikni na každý den, kdy můžeš, a vyber, od kolika. Stejným tlačítkem den změníš nebo zrušíš."
                 + (" Ikonka u dne = počasí večer." if weather else ""))
    embed = discord.Embed(
        title=f"🗓️ Kdy na pivo? {days[0].day}. {days[0].month}. – {days[-1].day}. {days[-1].month}.",
        description="\n".join(lines), color=COLOR, timestamp=p.created,
    )
    _footer(embed, "Založeno", weather is not None)
    fields = []
    for d, people in planning.by_day(p.votes).items():
        order = sorted(people.items(), key=lambda kv: (kv[1] or "00:00").zfill(5))
        value = "\n".join(f"<@{u}> · {_vote_text(t)}" for u, t in order)
        trophy = "🏆 " if best and d == best.day else ""
        fields.append(render.Field(f"{trophy}{planning.day_label(d)} ({len(people)})", value))
    render.add_fields(embed, fields, 5000)
    return embed


def read_plan(embed: discord.Embed | None) -> Plan | None:
    if embed is None or not (created := _created(embed)) or not (embed.title or "").startswith("🗓️"):
        return None
    plan = Plan(created, _creator(embed), read_place(embed))
    by_label = {planning.day_label(d): d for d in plan.days}
    for f in embed.fields:
        d = by_label.get(_COUNT_RE.sub("", (f.name or "").removeprefix("🏆 ")))
        if d is None:
            continue
        for user, time in _VOTE_RE.findall(f.value or ""):
            plan.votes.setdefault(int(user), {})[d] = time or None
    return plan


def plan_view(p: Plan, today: date, weather: openmeteo.Forecast | None = None) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    best = planning.best_day(p.votes, today)
    counts = {d: len(people) for d, people in planning.by_day(p.votes).items()}
    for i, d in enumerate(p.days):
        n = counts.get(d, 0)
        label = f"{planning.WEEKDAYS_SHORT[d.weekday()]} {d.day}." + (f" · {n}" if n else "")
        if best and d == best.day:
            style = discord.ButtonStyle.success
        elif n:
            style = discord.ButtonStyle.primary
        else:
            style = discord.ButtonStyle.secondary
        o = openmeteo.outlook(weather, d) if weather and d >= today else None
        view.add_item(DayButton(d, label=label, style=style, disabled=d < today, row=i // 5,
                                emoji=o.icon if o else None))
    view.add_item(PlaceSelect("pivokdy", p.place, row=3))
    view.add_item(CallButton(disabled=best is None, row=4))
    view.add_item(MapButton(row=4))
    view.add_item(ClearButton(row=4))
    return view


def plan_message(p: Plan, client) -> dict:
    today, weather = service.today(), forecast(client)
    return {"embed": plan_embed(p, today, weather), "view": plan_view(p, today, weather)}


def meetup_message(m: Meetup, client) -> dict:
    return {"embed": meetup_embed(m, forecast(client)), "view": meetup_view(m)}


# --- tlačítka a výběry -----------------------------------------------------------------------------


async def _edit(interaction: discord.Interaction, change) -> None:
    """Přečte stav ze zprávy, `change(stav)` ho upraví (vrací chybovou hlášku nebo None) a zprávu přepíše."""
    message = interaction.message
    async with _locks[message.id]:
        embed = message.embeds[0] if message.embeds else None
        state = read_plan(embed) or read_meetup(embed)
        if state is None:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        error = change(state)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
        elif isinstance(state, Plan):
            await interaction.response.edit_message(**plan_message(state, interaction.client))
        else:
            await interaction.response.edit_message(**meetup_message(state, interaction.client))


class AnswerButton(discord.ui.DynamicItem[discord.ui.Button], template=r"napivo:a:(?P<answer>[a-z]+)"):
    def __init__(self, answer: str, **button_kwargs) -> None:
        super().__init__(discord.ui.Button(custom_id=f"napivo:a:{answer}", **button_kwargs))
        self.answer = answer

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> AnswerButton:
        return cls(match["answer"])

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.answer not in ANSWERS:
            await interaction.response.send_message(STALE, ephemeral=True)
            return

        def change(m):
            if not isinstance(m, Meetup):
                return STALE
            m.apply(interaction.user.id, self.answer)

        await _edit(interaction, change)


class TimeSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"napivo:cas"):
    def __init__(self, current: str | None = None) -> None:
        options = [discord.SelectOption(label=t, value=t, emoji="🕐", default=t == current) for t in TIMES]
        super().__init__(discord.ui.Select(custom_id="napivo:cas", placeholder="🕐 V kolik?", options=options, row=0))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> TimeSelect:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        time = self.item.values[0] if self.item.values else None

        def change(m):
            if not isinstance(m, Meetup) or time not in TIMES:
                return STALE
            m.time = time

        await _edit(interaction, change)


class PlaceSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"(?P<kind>napivo|pivokdy):kam"):
    """Kam se jde – oblast („v centru“) nebo konkrétní podnik. Stejný výběr u obou druhů zpráv."""

    def __init__(self, kind: str, current: str | None = None, row: int | None = None) -> None:
        super().__init__(discord.ui.Select(
            custom_id=f"{kind}:kam", placeholder="📍 Kam se jde?", options=place_options(current), row=row,
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> PlaceSelect:
        return cls(match["kind"])

    async def callback(self, interaction: discord.Interaction) -> None:
        place = self.item.values[0] if self.item.values else None
        if place not in venues.PUBS and place not in venues.AREAS:
            await interaction.response.send_message(STALE, ephemeral=True)
            return

        def change(state):
            state.place = place

        await _edit(interaction, change)


class MapButton(discord.ui.DynamicItem[discord.ui.Button], template=r"napivo:mapa"):
    """🗺️ Kde co je – seznam podniků s mapou, vidí ho jen ten, kdo klikl."""

    def __init__(self, row: int | None = None) -> None:
        super().__init__(discord.ui.Button(custom_id="napivo:mapa", label="Kde co je", emoji="🗺️",
                                           style=discord.ButtonStyle.secondary, row=row))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> MapButton:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=map_embed(), ephemeral=True)


class PlanNewButton(discord.ui.DynamicItem[discord.ui.Button], template=r"napivo:termin"):
    """🗓️ Najít jiný den – pod pozvánkou založí hledání termínu (se stejným místem)."""

    def __init__(self, row: int | None = None) -> None:
        super().__init__(discord.ui.Button(custom_id="napivo:termin", label="Najít jiný den", emoji="🗓️",
                                           style=discord.ButtonStyle.secondary, row=row))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> PlanNewButton:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        embed = interaction.message.embeds[0] if interaction.message and interaction.message.embeds else None
        place = read_place(embed) if embed else None
        plan = Plan(_now(), str(interaction.user.id), place)
        await interaction.response.send_message(**plan_message(plan, interaction.client))


class DayModal(discord.ui.Modal):
    """Okno po kliknutí na den: od kolika můžu (nebo nemůžu)."""

    def __init__(self, day: date, current: str | None, voted: bool) -> None:
        super().__init__(title=f"🍺 {render.czech_date(day)}"[:45], timeout=900)
        self.day = day
        options = [
            discord.SelectOption(label="Nemůžu", value="x", emoji="❌", default=False),
            discord.SelectOption(label="Kdykoliv", value="any", emoji="✅", default=voted and current is None),
        ] + [
            discord.SelectOption(label=f"Od {t}", value=t, emoji="🕐", default=voted and current == t)
            for t in FROM_TIMES
        ]
        self.choice = discord.ui.Select(placeholder="Vyber, od kolika můžeš", options=options)
        self.add_item(discord.ui.Label(
            text="Od kolika ten den můžeš?", description="Když nemůžeš, vyber ❌ Nemůžu.", component=self.choice,
        ))

    async def on_submit(self, interaction: discord.Interaction) -> None:
        choice = self.choice.values[0] if self.choice.values else "x"

        def change(p):
            if not isinstance(p, Plan) or self.day not in p.days:
                return STALE
            p.vote(interaction.user.id, self.day, choice)

        await _edit(interaction, change)


class DayButton(discord.ui.DynamicItem[discord.ui.Button], template=r"pivokdy:d:(?P<day>\d{8})"):
    def __init__(self, day: date, **button_kwargs) -> None:
        super().__init__(discord.ui.Button(custom_id=f"pivokdy:d:{day:%Y%m%d}", **button_kwargs))
        self.day = day

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> DayButton:
        return cls(datetime.strptime(match["day"], "%Y%m%d").date())

    async def callback(self, interaction: discord.Interaction) -> None:
        plan = read_plan(interaction.message.embeds[0] if interaction.message.embeds else None)
        if plan is None or self.day not in plan.days:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        if self.day < service.today():
            await interaction.response.send_message("Tenhle den už je pryč. 🙂", ephemeral=True)
            return
        mine = plan.votes.get(interaction.user.id, {})
        await interaction.response.send_modal(DayModal(self.day, mine.get(self.day), self.day in mine))


class CallButton(discord.ui.DynamicItem[discord.ui.Button], template=r"pivokdy:svolat"):
    """🍺 Svolat – z nejlepšího termínu udělá pozvánku jako /na-pivo a označí ty, kdo ten den můžou."""

    def __init__(self, disabled: bool = False, row: int | None = None) -> None:
        super().__init__(discord.ui.Button(custom_id="pivokdy:svolat", label="Svolat nejlepší den", emoji="🍺",
                                           style=discord.ButtonStyle.success, disabled=disabled, row=row))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> CallButton:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        plan = read_plan(interaction.message.embeds[0] if interaction.message.embeds else None)
        if plan is None:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        best = planning.best_day(plan.votes, service.today())
        if best is None:
            await interaction.response.send_message("Zatím nikdo nemůže ani jeden den. 🦗", ephemeral=True)
            return
        meetup = Meetup(best.day, _now(), str(interaction.user.id), best.time, plan.place)
        when = render.czech_date(best.day) + (f" od {best.time}" if best.time else "")
        content = f"🍺 Jde se na pivo – {when}! " + " ".join(f"<@{u}>" for u in best.users)
        await interaction.response.send_message(content=content, **meetup_message(meetup, interaction.client))


class ClearButton(discord.ui.DynamicItem[discord.ui.Button], template=r"pivokdy:x"):
    def __init__(self, row: int | None = None) -> None:
        super().__init__(discord.ui.Button(custom_id="pivokdy:x", label="Smazat mě", emoji="❌",
                                           style=discord.ButtonStyle.danger, row=row))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> ClearButton:
        return cls()

    async def callback(self, interaction: discord.Interaction) -> None:
        def change(p):
            if not isinstance(p, Plan):
                return STALE
            p.votes.pop(interaction.user.id, None)

        await _edit(interaction, change)


DYNAMIC_ITEMS = (AnswerButton, TimeSelect, PlaceSelect, MapButton, PlanNewButton, DayButton, CallButton, ClearButton)


class NaPivo(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(*DYNAMIC_ITEMS)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(*DYNAMIC_ITEMS)

    @app_commands.command(name="na-pivo", description="🍺 Kdo jde dneska na pivo? Kdy, kam a kdo jde")
    async def na_pivo(self, interaction: discord.Interaction) -> None:
        meetup = Meetup(service.today(), _now(), str(interaction.user.id))
        await interaction.response.send_message(**meetup_message(meetup, self.bot))

    @app_commands.command(name="na-pivo-termin", description="🗓️ Najděte společný den na pivo v příštích dvou týdnech")
    async def na_pivo_termin(self, interaction: discord.Interaction) -> None:
        plan = Plan(_now(), str(interaction.user.id))
        await interaction.response.send_message(**plan_message(plan, interaction.client))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(NaPivo(bot))
