"""Točená piva v hospodách z /na-pivo: /co-toci (profil jedné hospody) a /cena-piva (přehled všech).

Zadat nebo opravit piva může kdokoli. Každá změna se pamatuje (storage/beer.py) i s tím, kdo ji udělal, a jde vrátit
na kterýkoli starší stav. Ceny se ukazují v /na-pivo (u vybraného podniku, ve výběru „Kam“ a v 🗺️ Kde co je).

Hospoda se všude ukazuje jako stejný profil (`profile`): kde je, všechna piva s cenou a odkdy platí, historie změn
a pod tím ovládání: ➕ Přidat pivo, 🍻 Víc druhů, ✏️ Upravit nebo smazat pivo, ↩️ Vrátit a výběr jiné hospody.
- /co-toci <hospoda> → profil pro všechny v kanálu,
- /cena-piva → přehled hospod jen pro sebe, výběr (`pivocena:p:e`) ho přepne na profil,
- 🗺️ Kde co je v /na-pivo → stejný výběr (`pivocena:p:n`), profil přijde jako nová zpráva jen pro sebe.
Po každé změně se profil překreslí ve zprávě, ze které se změna udělala.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

import discord
from discord import app_commands
from discord.ext import commands

from lunch.service import TZ
from pubs import beers, venues
from storage import beer, ready
from utils import render
from utils.interactions import STALE, reported
from utils.text import clean, plural

log = logging.getLogger(__name__)

HISTORY_SHOWN = 8
NAME_LIMIT = 40
FOOTER = "Ceny za 0,5 l · zadat, opravit i vrátit je může kdokoli"


async def reload(db) -> None:
    """Načte aktuální stav do `venues.beer_prices` (z něj kreslí /na-pivo)."""
    venues.beer_prices = {pub: s for pub, s in (await beer.current(db)).items() if pub in venues.PUBS}


def _day(d: date) -> str:
    return f"{d.day}. {d.month}. {d.year}"


def _when(v: beer.Version) -> str:
    return f"{_day(v.created_at)} {v.created_at:%H:%M}"


def overview() -> str:
    lines = [
        "### 🍺 Točená piva v hospodách",
        "-# Vyber hospodu a uvidíš všechna piva, můžeš je i doplnit nebo opravit. Pro všechny v kanálu: /co-toci.",
    ]
    for pub in venues.pubs_by_area():
        lines.append(f"{pub.emoji} **{pub.name}** — {pub.beer_text or '_nevíme_'}")
    return "\n".join(lines)


def overview_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(PubSelect("e"))
    return view


def profile_embed(pub: venues.Pub, versions: list[beer.Version]) -> discord.Embed:
    state = versions[0].state if versions else beers.PubBeers()
    area = venues.AREAS[pub.area]
    where = " · ".join(p for p in (f"{area.emoji} {area.label}", pub.address, f"[🗺️ mapa]({pub.map})") if p)
    lines = [f"📍 {where}"]
    if state.taps:
        prices = [t.price for t in state.taps]
        span = f"{min(prices)}–{max(prices)} Kč" if min(prices) != max(prices) else f"{prices[0]} Kč"
        lines.append(f"🍺 Točí **{plural(len(prices), 'pivo', 'piva', 'piv')}** · {span}")
    if state.empty:
        lines.append("_Zatím nikdo nezadal, co tu točí._ Klikni na ➕ Přidat pivo.")
    else:
        lines.append(f"-# Ve výpisech /na-pivo: {state.text}")
    embed = discord.Embed(title=f"{pub.emoji} {pub.name}", url=pub.map, description="\n".join(lines),
                          color=venues.COLOR)

    fields = [render.Field(f"🍺 {t.name}", f"**{t.price} Kč**\n-# od {_day(t.since)}") for t in state.taps]
    if state.many_price is not None:
        fields.append(render.Field(
            "🍻 Víc druhů", f"kolem **{state.many_price} Kč**\n-# ve výpisech místo seznamu piv", inline=False,
        ))
    if versions:
        history = [f"-# {_when(v)} · {v.change} · <@{v.user_id}>" for v in versions[:HISTORY_SHOWN]]
        fields.append(render.Field("🕓 Historie změn", render.fit_lines(history, render.FIELD_VALUE_LIMIT),
                                   inline=False))
    render.add_fields(embed, fields, render.TOTAL_BUDGET)
    embed.set_footer(text=FOOTER)
    return embed


async def profile(db, pub_key: str, notice: str = "") -> dict:
    """Profil hospody jako zpráva: `send_message(**profile(…))` nebo `edit_message(**profile(…))`."""
    pub = venues.PUBS[pub_key]
    versions = await beer.history(db, pub_key)
    state = versions[0].state if versions else beers.PubBeers()
    view = discord.ui.View(timeout=None)
    view.add_item(AddButton(pub_key))
    view.add_item(ManyButton(pub_key))
    if state.taps:
        view.add_item(TapSelect(pub_key, state.taps))
    if len(versions) > 1:
        view.add_item(RevertSelect(pub_key, versions[1:]))
    view.add_item(PubSelect("e", row=3, placeholder="🍺 Jiná hospoda…"))
    return {"content": notice or None, "embed": profile_embed(pub, versions), "view": view}


async def _save(interaction: discord.Interaction, pub_key: str, edit=None, back: beer.Version | None = None) -> None:
    """Uloží změnu podniku (`edit`, nebo vrácení na stav `back`) a překreslí profil s hláškou.
    Chybu zadání ukáže jen jako hlášku."""
    db = interaction.client.db
    now = datetime.now(TZ)
    try:
        if back is not None:
            version = await beer.revert(db, back, interaction.user.id, now)
        else:
            version = await beer.change(db, pub_key, edit, interaction.user.id, now)
    except beers.BeerError as exc:
        await interaction.response.send_message(str(exc), ephemeral=True)
        return
    await reload(db)
    await interaction.response.edit_message(**await profile(db, pub_key, f"✅ Uloženo: {version.change}"))


class TapModal(discord.ui.Modal):
    """Přidat pivo (`original` None), nebo upravit / smazat existující (prázdná cena = smazat)."""

    def __init__(self, pub_key: str, original: beers.Tap | None = None) -> None:
        pub = venues.PUBS[pub_key]
        super().__init__(title=f"🍺 {pub.name}"[:45], timeout=900)
        self.pub_key = pub_key
        self.original = original
        self.name = discord.ui.TextInput(
            placeholder="např. Plzeň 12°", min_length=2, max_length=NAME_LIMIT,
            default=original.name if original else None,
        )
        self.price = discord.ui.TextInput(
            placeholder="prázdné = pivo smazat" if original else "např. 59", required=original is None, max_length=6,
            default=str(original.price) if original else None,
        )
        self.add_item(discord.ui.Label(text="Pivo", component=self.name))
        self.add_item(discord.ui.Label(text="Cena za 0,5 l (Kč)", component=self.price))

    @reported
    async def on_submit(self, interaction: discord.Interaction) -> None:
        original = self.original.name if self.original else None
        try:
            price = beers.parse_price(self.price.value, required=original is None)
            name = clean(self.name.value, NAME_LIMIT)
            if price is not None and len(name) < 2:
                raise beers.BeerError("Napiš, jaké pivo to je, třeba `Plzeň 12°`.")
        except beers.BeerError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        if price is None:
            await _save(interaction, self.pub_key, lambda s: beers.remove(s, original))
        else:
            await _save(interaction, self.pub_key, lambda s: beers.add(s, name, price, original))


class ManyModal(discord.ui.Modal):
    def __init__(self, pub_key: str, current: int | None) -> None:
        pub = venues.PUBS[pub_key]
        super().__init__(title=f"🍻 {pub.name}"[:45], timeout=900)
        self.pub_key = pub_key
        self.price = discord.ui.TextInput(
            placeholder="např. 70 · prázdné = zrušit", required=False, max_length=6,
            default=str(current) if current is not None else None,
        )
        self.add_item(discord.ui.Label(
            text="Víc druhů, cena kolem (Kč za 0,5 l)", component=self.price,
            description="Pro hospody s velkým výběrem. Ve výpisech se pak ukáže místo seznamu piv.",
        ))

    @reported
    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            price = beers.parse_price(self.price.value, required=False)
        except beers.BeerError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        await _save(interaction, self.pub_key, lambda s: beers.set_many(s, price))


async def _current(interaction: discord.Interaction, pub_key: str) -> beers.PubBeers | None:
    """Aktuální stav podniku pro okno, None = už odpověděno hláškou."""
    if pub_key not in venues.PUBS:
        await interaction.response.send_message(STALE, ephemeral=True)
        return None
    versions = await beer.history(interaction.client.db, pub_key, limit=1)
    return versions[0].state if versions else beers.PubBeers()


class PubSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"pivocena:p:(?P<mode>[en])"):
    """Výběr podniku. `e` = přepne zprávu na profil, `n` = pošle profil jako novou zprávu (z Kde co je)."""

    def __init__(self, mode: str, row: int | None = None, placeholder: str = "🍺 Co kde točí…") -> None:
        options = [
            discord.SelectOption(label=pub.name, value=pub.key, emoji=pub.emoji,
                                 description=pub.beer.price_text or "cenu zatím nevíme")
            for pub in venues.pubs_by_area()
        ][:25]
        super().__init__(discord.ui.Select(
            custom_id=f"pivocena:p:{mode}", placeholder=placeholder, options=options, row=row,
        ))
        self.mode = mode

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> PubSelect:
        return cls(match["mode"])

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        pub_key = self.item.values[0] if self.item.values else None
        if pub_key not in venues.PUBS:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        shown = await profile(interaction.client.db, pub_key)
        if self.mode == "e":
            await interaction.response.edit_message(**shown)
        else:
            await interaction.response.send_message(**shown, ephemeral=True)


class _ForPub:
    """Tlačítka a výběry profilu: podnik je v custom_id (`pivocena:<akce>:<podnik>`)."""

    pub_key: str

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /):
        return cls(match["pub"])


class AddButton(_ForPub, discord.ui.DynamicItem[discord.ui.Button], template=r"pivocena:a:(?P<pub>[a-z0-9_]+)"):
    def __init__(self, pub_key: str) -> None:
        super().__init__(discord.ui.Button(
            custom_id=f"pivocena:a:{pub_key}", label="Přidat pivo", emoji="➕", style=discord.ButtonStyle.success,
            row=0,
        ))
        self.pub_key = pub_key

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        if self.pub_key not in venues.PUBS:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        await interaction.response.send_modal(TapModal(self.pub_key))


class ManyButton(_ForPub, discord.ui.DynamicItem[discord.ui.Button], template=r"pivocena:m:(?P<pub>[a-z0-9_]+)"):
    def __init__(self, pub_key: str) -> None:
        super().__init__(discord.ui.Button(
            custom_id=f"pivocena:m:{pub_key}", label="Víc druhů", emoji="🍻", style=discord.ButtonStyle.secondary,
            row=0,
        ))
        self.pub_key = pub_key

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        state = await _current(interaction, self.pub_key)
        if state is not None:
            await interaction.response.send_modal(ManyModal(self.pub_key, state.many_price))


class TapSelect(_ForPub, discord.ui.DynamicItem[discord.ui.Select], template=r"pivocena:e:(?P<pub>[a-z0-9_]+)"):
    """✏️ Upravit nebo smazat pivo: otevře okno s pivem (hodnota = název piva)."""

    def __init__(self, pub_key: str, taps: tuple[beers.Tap, ...] = ()) -> None:
        options = [discord.SelectOption(label=t.name, value=t.name, description=f"{t.price} Kč") for t in taps]
        super().__init__(discord.ui.Select(
            custom_id=f"pivocena:e:{pub_key}", placeholder="✏️ Upravit nebo smazat pivo…", options=options[:25],
            row=1,
        ))
        self.pub_key = pub_key

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        state = await _current(interaction, self.pub_key)
        if state is None:
            return
        tap = state.find(self.item.values[0]) if self.item.values else None
        if tap is None:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        await interaction.response.send_modal(TapModal(self.pub_key, tap))


class RevertSelect(_ForPub, discord.ui.DynamicItem[discord.ui.Select], template=r"pivocena:v:(?P<pub>[a-z0-9_]+)"):
    """↩️ Vrátit na starší stav (třeba když někdo zadal nesmysl). Hodnota = id stavu."""

    def __init__(self, pub_key: str, older: list[beer.Version] | None = None) -> None:
        options = [
            discord.SelectOption(label=(v.state.summary or "nic nezadáno")[:100], value=str(v.id),
                                 description=f"{_when(v)} · {v.change}"[:100])
            for v in (older or [])[:25]
        ]
        super().__init__(discord.ui.Select(
            custom_id=f"pivocena:v:{pub_key}", placeholder="↩️ Vrátit na starší stav…", options=options, row=2,
        ))
        self.pub_key = pub_key

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.item.values[0] if self.item.values else ""
        version = await beer.get(interaction.client.db, int(value)) if value.isdigit() else None
        if version is None or version.pub != self.pub_key or self.pub_key not in venues.PUBS:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        await _save(interaction, self.pub_key, back=version)


ITEMS = (PubSelect, AddButton, ManyButton, TapSelect, RevertSelect)
PUB_CHOICES = [app_commands.Choice(name=pub.name, value=pub.key) for pub in venues.pubs_by_area()][:25]


class CenaPiva(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(*ITEMS)
        db = getattr(self.bot, "db", None)
        if ready(db):
            try:
                await reload(db)
            except Exception:
                log.exception("Načtení cen piva selhalo")

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(*ITEMS)

    @app_commands.command(name="co-toci", description="🍺 Co točí v hospodě: všechna piva, ceny a odkdy platí")
    @app_commands.describe(hospoda="Která hospoda")
    @app_commands.choices(hospoda=PUB_CHOICES)
    async def co_toci(self, interaction: discord.Interaction, hospoda: app_commands.Choice[str]) -> None:
        if hospoda.value not in venues.PUBS:
            await interaction.response.send_message(overview(), view=overview_view(), ephemeral=True)
            return
        await interaction.response.send_message(**await profile(self.bot.db, hospoda.value))

    @app_commands.command(name="cena-piva", description="🍺 Točená piva a ceny ve všech hospodách – zadat, opravit, vrátit")
    async def cena_piva(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(overview(), view=overview_view(), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CenaPiva(bot))
