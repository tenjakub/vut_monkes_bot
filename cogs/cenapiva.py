"""/cena-piva – ceny točeného piva v hospodách z /na-pivo. Zadat nebo opravit je může kdokoli.

Každá změna se pamatuje (storage/beer.py) i s tím, kdo ji udělal, a jde vrátit výběrem „↩️ Vrátit na…“.
Ceny se pak ukazují v /na-pivo (u vybraného podniku a v 🗺️ Kde co je). Všechno je jen pro toho, kdo klikl.

- /cena-piva → přehled podniků s cenami + výběr podniku (`pivocena:p:e`),
- /cena-piva podnik:… nebo výběr → karta podniku: cena, historie, ✏️ Upravit (okno), ↩️ Vrátit na…,
- 🗺️ Kde co je v /na-pivo má stejný výběr (`pivocena:p:n`), ten kartu pošle jako novou zprávu (mapa zůstane).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from lunch.service import TZ
from pubs import venues
from storage import DatabaseUnavailable, beer
from utils.interactions import STALE, reported

log = logging.getLogger(__name__)

UNAVAILABLE = "Databáze teď není dostupná 😵 Ceny piva zkus prosím později."
MIN_PRICE, MAX_PRICE = 10, 500  # Kč za 0,5 l, víc nebo míň je skoro jistě překlep
_PRICE_RE = re.compile(r"^\s*(\d+)\s*(?:kč|,-|,00)?\s*$", re.IGNORECASE)
MANY_YES, MANY_NO = "many", "one"


def checked(entry: beer.BeerEntry) -> str:
    return f"{entry.created_at.month}/{entry.created_at.year}"


def as_beer(entry: beer.BeerEntry) -> venues.Beer:
    return venues.Beer(entry.price or 0, entry.beer, entry.many, checked(entry))


async def reload(db) -> None:
    """Načte aktuální ceny do `venues.beer_prices` (z nich kreslí /na-pivo)."""
    venues.beer_prices = {pub: as_beer(e) for pub, e in (await beer.current(db)).items() if pub in venues.PUBS}


def parse_price(text: str) -> int | None:
    """'59' / '59 Kč' / '59,-' -> 59; prázdné -> None (= smazat); nesmysl -> ValueError."""
    if not text.strip():
        return None
    m = _PRICE_RE.match(text)
    if not m or not MIN_PRICE <= int(m.group(1)) <= MAX_PRICE:
        raise ValueError(text)
    return int(m.group(1))


def entry_text(e: beer.BeerEntry) -> str:
    if e.price is None:
        return "🚫 cena smazaná"
    return as_beer(e).text.rsplit(" (", 1)[0]  # bez „(11/2026)“, datum je v historii zvlášť


def _when(e: beer.BeerEntry) -> str:
    return f"{e.created_at.day}. {e.created_at.month}. {e.created_at.year}"


def overview() -> str:
    lines = [
        "### 🍺 Ceny točeného piva",
        "-# Cena za 0,5 l. Zadat nebo opravit ji může kdokoli, každá změna se pamatuje a jde vrátit. "
        "Ceny se ukazují v /na-pivo.",
    ]
    for area in venues.AREAS.values():
        for pub in venues.pubs_in(area.key):
            lines.append(f"{pub.emoji} **{pub.name}** — {pub.beer_text or '_nevíme_'}")
    return "\n".join(lines)


def overview_view() -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    view.add_item(PubSelect("e"))
    return view


async def card(db, pub_key: str, notice: str = "") -> tuple[str, discord.ui.View]:
    pub = venues.PUBS[pub_key]
    entries = await beer.history(db, pub_key)
    lines = [notice] if notice else []
    head = " · ".join(p for p in (pub.address, f"[🗺️ mapa]({pub.map})") if p)
    lines += [f"### {pub.emoji} {pub.name}", f"-# {head}"]
    now = entries[0] if entries else None
    if now and now.price is not None:
        lines.append(f"**Teď:** {entry_text(now)} · zadáno {_when(now)}")
    else:
        lines.append("_Cenu zatím nikdo nezadal._ Klikni na ✏️ Upravit.")
    if entries:
        lines.append("**Historie změn**")
        for e in entries[:10]:
            back = " (vráceno)" if e.reverted_from else ""
            lines.append(f"-# {_when(e)} · {entry_text(e)}{back} · <@{e.user_id}>")
    view = discord.ui.View(timeout=None)
    view.add_item(EditButton(pub_key))
    view.add_item(BackButton())
    older = entries[1:]
    if older:
        view.add_item(RevertSelect(pub_key, older))
    return "\n".join(lines), view


class PriceModal(discord.ui.Modal):
    def __init__(self, pub_key: str, now: beer.BeerEntry | None) -> None:
        pub = venues.PUBS[pub_key]
        super().__init__(title=f"🍺 {pub.name}"[:45], timeout=900)
        self.pub_key = pub_key
        has_price = now is not None and now.price is not None
        self.price = discord.ui.TextInput(
            placeholder="např. 59 · prázdné = cenu smazat", required=False, max_length=6,
            default=str(now.price) if has_price else None,
        )
        self.beer = discord.ui.TextInput(
            placeholder="např. Plzeň 12° (nepovinné)", required=False, max_length=40,
            default=now.beer if has_price and now.beer else None,
        )
        many = has_price and now.many
        self.many = discord.ui.Select(options=[
            discord.SelectOption(label="Jedno pivo", value=MANY_NO, emoji="🍺", default=not many),
            discord.SelectOption(label="Víc druhů (cena je orientační)", value=MANY_YES, emoji="🍻", default=many),
        ])
        self.add_item(discord.ui.Label(text="Cena za 0,5 l (Kč)", component=self.price))
        self.add_item(discord.ui.Label(text="Jaké pivo", component=self.beer))
        self.add_item(discord.ui.Label(text="Kolik druhů točí", component=self.many))

    @reported
    async def on_submit(self, interaction: discord.Interaction) -> None:
        try:
            price = parse_price(self.price.value)
        except ValueError:
            await interaction.response.send_message(
                f"Cenu „{self.price.value}“ nechápu 🤔 Napiš celé číslo v Kč za půllitr ({MIN_PRICE}–{MAX_PRICE}).",
                ephemeral=True,
            )
            return
        many = (self.many.values or [MANY_NO])[0] == MANY_YES
        name = " ".join(self.beer.value.split())
        db = interaction.client.db
        try:
            await beer.add(db, self.pub_key, price, name if price else "", many and price is not None,
                           interaction.user.id, datetime.now(TZ))
            await reload(db)
            notice = "✅ Uloženo, díky!" if price is not None else "🚫 Cena smazaná."
            content, view = await card(db, self.pub_key, notice)
        except DatabaseUnavailable:
            await interaction.response.send_message(UNAVAILABLE, ephemeral=True)
            return
        await interaction.response.edit_message(content=content, embed=None, view=view)


class PubSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"pivocena:p:(?P<mode>[en])"):
    """Výběr podniku. `e` = upraví zprávu (přehled /cena-piva), `n` = pošle novou (z Kde co je)."""

    def __init__(self, mode: str, row: int | None = None) -> None:
        options = [
            discord.SelectOption(label=pub.name, value=pub.key, emoji=pub.emoji,
                                 description=pub.beer.price_text if pub.beer else "cenu zatím nevíme")
            for area in venues.AREAS.values() for pub in venues.pubs_in(area.key)
        ][:25]
        super().__init__(discord.ui.Select(
            custom_id=f"pivocena:p:{mode}", placeholder="🍺 Zadat nebo opravit cenu piva…", options=options, row=row,
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
        try:
            content, view = await card(interaction.client.db, pub_key)
        except DatabaseUnavailable:
            await interaction.response.send_message(UNAVAILABLE, ephemeral=True)
            return
        if self.mode == "e":
            await interaction.response.edit_message(content=content, embed=None, view=view)
        else:
            await interaction.response.send_message(content, view=view, ephemeral=True)


class EditButton(discord.ui.DynamicItem[discord.ui.Button], template=r"pivocena:u:(?P<pub>[a-z0-9_]+)"):
    def __init__(self, pub_key: str) -> None:
        super().__init__(discord.ui.Button(
            custom_id=f"pivocena:u:{pub_key}", label="Upravit", emoji="✏️", style=discord.ButtonStyle.primary,
        ))
        self.pub_key = pub_key

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> EditButton:
        return cls(match["pub"])

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        if self.pub_key not in venues.PUBS:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        try:
            entries = await beer.history(interaction.client.db, self.pub_key, limit=1)
        except DatabaseUnavailable:
            await interaction.response.send_message(UNAVAILABLE, ephemeral=True)
            return
        await interaction.response.send_modal(PriceModal(self.pub_key, entries[0] if entries else None))


class BackButton(discord.ui.DynamicItem[discord.ui.Button], template=r"pivocena:o"):
    def __init__(self) -> None:
        super().__init__(discord.ui.Button(
            custom_id="pivocena:o", label="Všechny podniky", emoji="📋", style=discord.ButtonStyle.secondary,
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> BackButton:
        return cls()

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.edit_message(content=overview(), embed=None, view=overview_view())


class RevertSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"pivocena:v:(?P<pub>[a-z0-9_]+)"):
    """↩️ Vrátit na starší záznam (třeba když někdo zadal nesmysl)."""

    def __init__(self, pub_key: str, older: list[beer.BeerEntry] | None = None) -> None:
        options = [
            discord.SelectOption(label=entry_text(e)[:100], value=str(e.id), description=f"zadáno {_when(e)}")
            for e in (older or [])[:25]
        ]
        super().__init__(discord.ui.Select(
            custom_id=f"pivocena:v:{pub_key}", placeholder="↩️ Vrátit na starší cenu…", options=options,
        ))
        self.pub_key = pub_key

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> RevertSelect:
        return cls(match["pub"])

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.item.values[0] if self.item.values else ""
        db = interaction.client.db
        try:
            entry = await beer.get(db, int(value)) if value.isdigit() else None
            if entry is None or entry.pub != self.pub_key or self.pub_key not in venues.PUBS:
                await interaction.response.send_message(STALE, ephemeral=True)
                return
            await beer.revert(db, entry, interaction.user.id, datetime.now(TZ))
            await reload(db)
            content, view = await card(db, self.pub_key, f"↩️ Vráceno na: {entry_text(entry)} (z {_when(entry)}).")
        except DatabaseUnavailable:
            await interaction.response.send_message(UNAVAILABLE, ephemeral=True)
            return
        await interaction.response.edit_message(content=content, view=view)


ITEMS = (PubSelect, EditButton, BackButton, RevertSelect)
PUB_CHOICES = [
    app_commands.Choice(name=pub.name, value=pub.key)
    for area in venues.AREAS.values() for pub in venues.pubs_in(area.key)
][:25]


class CenaPiva(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(*ITEMS)
        db = getattr(self.bot, "db", None)
        if db is not None and db.is_open:
            try:
                await reload(db)
            except Exception:
                log.exception("Načtení cen piva selhalo")

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(*ITEMS)

    @app_commands.command(name="cena-piva", description="🍺 Ceny točeného piva v hospodách – zadat, opravit, vrátit")
    @app_commands.describe(podnik="Rovnou otevřít konkrétní podnik")
    @app_commands.choices(podnik=PUB_CHOICES)
    async def cena_piva(self, interaction: discord.Interaction, podnik: app_commands.Choice[str] | None = None) -> None:
        if podnik is None or podnik.value not in venues.PUBS:
            await interaction.response.send_message(overview(), view=overview_view(), ephemeral=True)
            return
        try:
            content, view = await card(self.bot.db, podnik.value)
        except DatabaseUnavailable:
            await interaction.response.send_message(UNAVAILABLE, ephemeral=True)
            return
        await interaction.response.send_message(content, view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CenaPiva(bot))
