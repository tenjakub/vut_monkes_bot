"""/hlidat – hlídání akcí. Když se v Lidlu, BILLE, Albertu nebo Globusu objeví akce na hlídanou věc (jakákoli
akce, nebo do zadané ceny za kus), bot napíše do soukromé zprávy.

- Hledá se v tom, co bot z Kupi.cz stahuje (maso, nápoje, pivo), kontroluje se po každé obnově (1× za hodinu).
- O každé akci dá vědět jen jednou. Co platí už při přidání hlídání, se ukáže hned (a zprávou se neposílá).
- Správa je zpráva jen pro toho, kdo ji otevřel: ➕ Přidat (okno) a výběr 🗑️ Zrušit hlídání.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import discord
from discord import app_commands
from discord.ext import commands

from cogs import slevy
from lunch.service import TZ, today
from shops import kupi, watching
from storage import ready, watches
from utils import render
from utils.interactions import STALE, reported
from utils.text import clean, parse_price, plural

log = logging.getLogger(__name__)

MAX_LINES = 5  # akcí na jedno hlídání (ve zprávě i po přidání)
MESSAGE_LIMIT = 1900
INTRO = (
    "-# Když se v Lidlu, BILLE, Albertu nebo Globusu objeví akce na to, co hlídáš, napíšu ti do soukromé zprávy. "
    "Hledá se v mase, nápojích a pivu, kontroluje se jednou za hodinu."
)


def _number(value: float) -> str:
    return f"{value:.0f}" if value == int(value) else f"{value:.2f}".replace(".", ",")


def label(w: watches.Watch) -> str:
    return f"**{w.query}**" + (f" do {_number(w.max_price)} Kč" if w.max_price is not None else " v akci")


def _deals(client) -> tuple[list[kupi.Deal], dict[str, str]]:
    """Načtené akce a jejich 🔥/🎣 z cogu Slevy (nic nestahuje)."""
    cog = client.get_cog("Slevy") if hasattr(client, "get_cog") else None
    if cog is None:
        return [], {}
    return cog.shops.all_deals(), cog.marks


def deal_lines(found: list[kupi.Deal], marks: dict[str, str]) -> list[str]:
    day = today()
    lines = [slevy.describe_deal(d, day, marks.get(d.id)) for d in found[:MAX_LINES]]
    if len(found) > MAX_LINES:
        lines.append(f"-# …a další ({len(found) - MAX_LINES})")
    return lines


async def manager(client, user_id: int, notice: list[str] | None = None) -> tuple[str, discord.ui.View]:
    """Přehled hlídání člověka s tlačítky (vidí ho jen on)."""
    mine = await watches.of_user(client.db, user_id)
    deals, _ = _deals(client)
    day = today()
    lines = list(notice or []) + ["### 🔔 Hlídání akcí", INTRO]
    if not mine:
        lines.append("_Zatím nic nehlídáš. Klikni na ➕ Přidat._")
    for w in mine:
        found = watching.matches(w.query, w.max_price, deals, day)
        lines.append(f"🔔 {label(w)} — " + (f"teď {plural(len(found), 'akce', 'akce', 'akcí')}" if found else "teď nic"))
    view = discord.ui.View(timeout=None)
    view.add_item(AddButton(disabled=len(mine) >= watches.MAX_PER_USER))
    if mine:
        view.add_item(RemoveSelect(mine))
    return render.fit_lines(lines, MESSAGE_LIMIT), view


class WatchModal(discord.ui.Modal):
    def __init__(self) -> None:
        super().__init__(title="🔔 Hlídat akci", timeout=900)
        self.query = discord.ui.TextInput(placeholder="např. Monster, Plzeň, kuřecí prsa", min_length=2, max_length=40)
        self.price = discord.ui.TextInput(placeholder="prázdné = dát vědět o každé akci", required=False, max_length=8)
        self.add_item(discord.ui.Label(text="Co hlídat", component=self.query))
        self.add_item(discord.ui.Label(
            text="Cena do (Kč za kus)", description="U balení po víc kusech se počítá cena za kus.", component=self.price,
        ))

    @reported
    async def on_submit(self, interaction: discord.Interaction) -> None:
        query = clean(self.query.value)
        try:
            max_price = parse_price(self.price.value)
        except ValueError:
            await interaction.response.send_message(
                f"Cenu „{self.price.value}“ nechápu 🤔 Napiš jen číslo, třeba `25` nebo `25,90`.", ephemeral=True
            )
            return
        if not watching.words(query):
            await interaction.response.send_message("Napiš, co mám hlídat, třeba `Monster`.", ephemeral=True)
            return
        db = interaction.client.db
        try:
            w = await watches.add(db, interaction.user.id, query, max_price, datetime.now(TZ))
        except watches.TooMany:
            await interaction.response.send_message(
                f"Hlídat jde nejvýš {watches.MAX_PER_USER} věcí, nejdřív nějakou zruš.", ephemeral=True
            )
            return
        deals, marks = _deals(interaction.client)
        found = watching.matches(w.query, w.max_price, deals, today())
        # co platí už teď, se ukáže tady a zprávou se pak neposílá
        await watches.mark_known(db, [(w.id, watching.hit_key(d)) for d in found], datetime.now(TZ))
        notice = [f"✅ Hlídám {label(w)}."]
        notice += ["**Teď v akci:**", *deal_lines(found, marks)] if found else ["-# Teď nic takového v akci není."]
        content, view = await manager(interaction.client, interaction.user.id, notice)
        await interaction.response.edit_message(content=content, view=view)


class AddButton(discord.ui.DynamicItem[discord.ui.Button], template=r"hlidat:pridat"):
    def __init__(self, disabled: bool = False) -> None:
        super().__init__(discord.ui.Button(
            custom_id="hlidat:pridat", label="Přidat", emoji="➕", style=discord.ButtonStyle.success,
            disabled=disabled, row=0,
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> AddButton:
        return cls()

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(WatchModal())


class RemoveSelect(discord.ui.DynamicItem[discord.ui.Select], template=r"hlidat:zrusit"):
    def __init__(self, mine: list[watches.Watch] | None = None) -> None:
        options = [
            discord.SelectOption(label=label(w).replace("**", "")[:100], value=str(w.id), emoji="🗑️")
            for w in mine or []
        ]
        super().__init__(discord.ui.Select(
            custom_id="hlidat:zrusit", placeholder="🗑️ Zrušit hlídání…", options=options, row=1,
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> RemoveSelect:
        return cls()

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        value = self.item.values[0] if self.item.values else ""
        mine = {w.id: w for w in await watches.of_user(interaction.client.db, interaction.user.id)}
        w = mine.get(int(value)) if value.isdigit() else None
        if w is None:
            await interaction.response.send_message(STALE, ephemeral=True)
            return
        await watches.remove(interaction.client.db, interaction.user.id, w.id)
        content, view = await manager(interaction.client, interaction.user.id, [f"🗑️ Už nehlídám {label(w)}."])
        await interaction.response.edit_message(content=content, view=view)


class MenuButton(discord.ui.DynamicItem[discord.ui.Button], template=r"hlidat:menu"):
    """Pod zprávou s akcemi: otevře správu hlídání."""

    def __init__(self) -> None:
        super().__init__(discord.ui.Button(
            custom_id="hlidat:menu", label="Upravit hlídání", emoji="🔔", style=discord.ButtonStyle.secondary,
        ))

    @classmethod
    async def from_custom_id(cls, interaction, item, match: re.Match[str], /) -> MenuButton:
        return cls()

    @reported
    async def callback(self, interaction: discord.Interaction) -> None:
        content, view = await manager(interaction.client, interaction.user.id)
        await interaction.response.send_message(content, view=view, ephemeral=True)


def notification(items: list[tuple[watches.Watch, list[kupi.Deal]]], marks: dict[str, str]) -> str:
    lines = ["🔔 **Nové akce na to, co hlídáš**"]
    for w, found in items:
        lines += ["", label(w), *deal_lines(found, marks)]
    lines += ["", "-# Hlídání upravíš tlačítkem níž nebo v /hlidat. Data z Kupi.cz."]
    return render.fit_lines(lines, MESSAGE_LIMIT)


ITEMS = (AddButton, RemoveSelect, MenuButton)


class Hlidat(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(*ITEMS)

    async def cog_unload(self) -> None:
        self.bot.remove_dynamic_items(*ITEMS)

    @commands.Cog.listener()
    async def on_deals_refreshed(self) -> None:
        """Po obnově slev (cog Slevy) projde hlídání a pošle zprávy o nových akcích."""
        try:
            await self.notify()
        except Exception:
            log.exception("Hlídání akcí selhalo")

    async def _send(self, user_id: int, text: str) -> bool:
        """Pošle zprávu. True = vyřízeno (poslané, nebo to nejde a nemá cenu to zkoušet znovu)."""
        try:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            view = discord.ui.View(timeout=None)
            view.add_item(MenuButton())
            await user.send(text, view=view)
            return True
        except (discord.Forbidden, discord.NotFound):
            log.info("Uživateli %s nejde poslat soukromá zpráva (má je vypnuté?)", user_id)
            return True
        except discord.HTTPException:
            log.exception("Poslání zprávy o akcích selhalo, zkusím to příště")
            return False

    async def notify(self) -> int:
        """Pošle zprávy o nových akcích. Vrací počet lidí, kterým se psalo."""
        db = getattr(self.bot, "db", None)
        if not ready(db):
            return 0
        deals, marks = _deals(self.bot)
        if not deals:
            return 0
        everything = await watches.everything(db)
        known = await watches.known_deals(db, [w.id for w in everything])
        day = today()
        per_user: dict[int, list[tuple[watches.Watch, list[kupi.Deal]]]] = {}
        for w in everything:
            new = [d for d in watching.matches(w.query, w.max_price, deals, day)
                   if (w.id, watching.hit_key(d)) not in known]
            if new:
                per_user.setdefault(w.user_id, []).append((w, new))
        sent = 0
        for user_id, items in per_user.items():
            if await self._send(user_id, notification(items, marks)):
                sent += 1
                hits = [(w.id, watching.hit_key(d)) for w, found in items for d in found]
                await watches.mark_known(db, hits, datetime.now(TZ))
        return sent

    @app_commands.command(name="hlidat", description="🔔 Hlídání akcí: napíšu ti, když bude v akci, co chceš (i do ceny)")
    async def hlidat(self, interaction: discord.Interaction) -> None:
        content, view = await manager(self.bot, interaction.user.id)
        await interaction.response.send_message(content, view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Hlidat(bot))
