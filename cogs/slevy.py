"""/slevy (akční letáky) a /maso (slevy na maso) pro vybrané supermarkety, data z Kupi.cz."""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from lunch import emoji
from lunch.service import today
from shops import kupi
from shops.service import MEAT_CATEGORIES, STORES, Shops, Store
from utils import render

log = logging.getLogger(__name__)

VIEW_LEAFLETS = "letaky"
VIEW_MEAT = "maso"
ALL = "vse"
MAX_DEALS = 10  # akcí na obchod
MAX_LEAFLETS = 5
SHORT_DAYS = ["po", "út", "st", "čt", "pá", "so", "ne"]
MEAT_FILTERS = {ALL: ("🥩", "Všechno"), **{k: v for k, v in MEAT_CATEGORIES.items() if k != "ostatni-maso"}}


def _short_date(d: date) -> str:
    return f"{SHORT_DAYS[d.weekday()]} {d.day}. {d.month}."


def _validity(valid_from: date | None, valid_to: date | None, day: date) -> str:
    if valid_from and valid_from > day:
        return f"🔜 od {_short_date(valid_from)}"
    if valid_to == day:
        return "⏳ končí dnes"
    if valid_to and valid_to == day + timedelta(days=1):
        return "⏳ končí zítra"
    return f"do {_short_date(valid_to)}" if valid_to else ""


def _fit(lines: list[str], limit: int, more_text: str) -> str:
    out, used = [], 0
    for i, line in enumerate(lines):
        if used + len(line) + 1 + len(more_text) + 10 > limit:
            out.append(more_text.format(n=len(lines) - i))
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


# --- letáky ---------------------------------------------------------------------------------


def _hours_line(store: Store, pages: dict[str, kupi.StorePage | None], day: date) -> str | None:
    hours = {b.label: (pages.get(b.kupi_path) or kupi.StorePage(None, {}, [])).hours.get(day.weekday()) for b in store.branches}
    known = {k: v for k, v in hours.items() if v}
    if not known:
        return None
    if len(set(known.values())) == 1:  # všude stejně -> pobočky jsou už v řádku 📍
        return f"🕐 Dnes {next(iter(known.values()))}"
    return "🕐 Dnes " + " · ".join(f"{k} {v}" for k, v in known.items())


def _leaflets_embed(store: Store, pages: dict[str, kupi.StorePage | None], day: date) -> discord.Embed:
    first = store.branches[0]
    embed = discord.Embed(
        title=f"{store.emoji} {store.name}",
        url=f"{kupi.BASE}/obchod/{first.kupi_path}",  # unikátní pro každý obchod
        color=store.color,
    )
    leaflets: dict[str, kupi.Leaflet] = {}
    for b in store.branches:
        page = pages.get(b.kupi_path)
        for leaflet in page.leaflets if page else []:
            leaflets.setdefault(leaflet.url, leaflet)
    valid = [l for l in leaflets.values() if not (l.valid_to and l.valid_to < day)]
    # platné teď (podle konce platnosti), pak budoucí (podle začátku)
    valid.sort(key=lambda l: (bool(l.valid_from and l.valid_from > day), l.valid_from or day, l.valid_to or date.max))

    lines = []
    if len(store.branches) > 1:
        lines.append("📍 " + ", ".join(b.label for b in store.branches))
    hours = _hours_line(store, pages, day)
    if hours:
        lines.append(hours)
    if all(pages.get(b.kupi_path) is None for b in store.branches):
        lines.append("⚠️ Letáky se nepodařilo načíst.")
    elif not valid:
        lines.append("_Teď tu žádný leták není._")
    for l in valid[:MAX_LEAFLETS]:
        when = _validity(l.valid_from, l.valid_to, day)
        lines.append(f"📰 [{l.title}]({l.url})" + (f" · {when}" if when else ""))
    embed.description = "\n".join(lines)
    current = next((l for l in valid if l.image and not (l.valid_from and l.valid_from > day)), None)
    if current:
        embed.set_thumbnail(url=current.image)
    return embed


# --- maso -----------------------------------------------------------------------------------


def _deal_line(d: kupi.Deal, day: date) -> str:
    icon = emoji.for_name(d.product)
    if icon == emoji.FALLBACK:
        icon = MEAT_CATEGORIES.get(d.category, ("🥩",))[0]
    name = d.product if len(d.product) <= 55 else d.product[:54] + "…"
    amount = f" {d.amount}" if d.amount else ""
    pct = f" `−{d.percent} %`" if d.percent else ""
    when = _validity(d.valid_from, d.valid_to, day)
    return f"{icon} {name}{amount} — **{d.price}**{pct}" + (f" · {when}" if when else "")


def store_deals(deals: list[kupi.Deal], store: Store, meat_filter: str, day: date) -> list[kupi.Deal]:
    """Akce obchodu: nejdřív platné teď podle slevy (bez % na konec), pak budoucí."""
    mine = [
        d
        for d in deals
        if d.shop in store.shop_labels
        and (meat_filter == ALL or d.category == meat_filter)
        and not (d.valid_to and d.valid_to < day)
    ]
    return sorted(mine, key=lambda d: (not d.is_current(day), -(d.percent or 0), d.product))


def _meat_embed(store: Store, deals: list[kupi.Deal], meat_filter: str, day: date, limit: int, error: bool) -> discord.Embed:
    icon, label = MEAT_FILTERS[meat_filter]
    embed = discord.Embed(
        title=f"{icon} {store.name}" + ("" if meat_filter == ALL else f" · {label}"),
        url=f"{kupi.BASE}/slevy/maso-drubez-a-ryby/{store.kupi_chain}",  # unikátní pro každý obchod
        color=store.color,
    )
    mine = store_deals(deals, store, meat_filter, day)
    if mine:
        lines = [_deal_line(d, day) for d in mine[:MAX_DEALS]]
        rest = len(mine) - len(lines)
        text = _fit(lines, limit, "_…a dalších {n} na Kupi.cz_")
        if rest > 0 and "a dalších" not in text:
            text += f"\n_…a dalších {rest} na Kupi.cz_"
        embed.description = text
    elif error:
        embed.description = "⚠️ Slevy se nepodařilo načíst."
    else:
        embed.description = "_Teď tu žádné slevy na maso nejsou._"
    return embed


# --- zpráva a tlačítka ------------------------------------------------------------------------


async def build_message(
    shops: Shops, view: str, meat_filter: str = ALL, force: bool = False
) -> tuple[str, list[discord.Embed], discord.ui.View]:
    day = today()
    stores = list(STORES.values())
    if view == VIEW_MEAT:
        result = await shops.meat_deals(force=force)
        limit = render.per_embed_limit(len(stores))
        embeds = [_meat_embed(s, result.deals, meat_filter, day, limit, bool(result.errors)) for s in stores]
        title = "🥩 Slevy na maso"
        fetched = result.fetched_at
    else:
        pages = await shops.store_pages(force=force)
        embeds = [_leaflets_embed(s, pages, day) for s in stores]
        title = "🛒 Akční letáky"
        fetched = None
    info = "Data z [Kupi.cz](https://www.kupi.cz)"
    if fetched:
        info += f" · aktualizováno <t:{int(fetched)}:R>"
    content = f"### {title} – {render.czech_date(day)}\n{info}"
    return content, embeds, build_view(view, meat_filter)


class SlevyButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"slevy:(?P<view>[a-z]+):(?P<filter>[a-z-]+):(?P<slot>[gfr])",
):
    """slot: g = přepnutí letáky/maso, f = filtr druhu masa, r = obnovit"""

    def __init__(self, view: str, meat_filter: str, slot: str, **button_kwargs) -> None:
        super().__init__(discord.ui.Button(custom_id=f"slevy:{view}:{meat_filter}:{slot}", **button_kwargs))
        self.view_name = view
        self.meat_filter = meat_filter
        self.slot = slot

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> SlevyButton:
        return cls(match["view"], match["filter"], match["slot"])

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.view_name not in (VIEW_LEAFLETS, VIEW_MEAT) or self.meat_filter not in MEAT_FILTERS:
            await interaction.response.send_message("Tohle tlačítko už je zastaralé.", ephemeral=True)
            return
        await interaction.response.defer()
        cog = interaction.client.get_cog("Slevy")  # type: ignore[attr-defined]
        content, embeds, view = await build_message(cog.shops, self.view_name, self.meat_filter, force=self.slot == "r")
        await interaction.edit_original_response(content=content, embeds=embeds, view=view)


def build_view(view: str, meat_filter: str) -> discord.ui.View:
    ui = discord.ui.View(timeout=None)

    def style(current: bool) -> discord.ButtonStyle:
        return discord.ButtonStyle.primary if current else discord.ButtonStyle.secondary

    ui.add_item(SlevyButton(VIEW_LEAFLETS, ALL, "g", label="Letáky", emoji="📰",
                            style=style(view == VIEW_LEAFLETS), disabled=view == VIEW_LEAFLETS, row=0))
    ui.add_item(SlevyButton(VIEW_MEAT, ALL, "g", label="Maso", emoji="🥩",
                            style=style(view == VIEW_MEAT and meat_filter == ALL),
                            disabled=view == VIEW_MEAT and meat_filter == ALL, row=0))
    ui.add_item(SlevyButton(view, meat_filter, "r", label="Obnovit", emoji="🔄", style=discord.ButtonStyle.secondary, row=0))
    ui.add_item(discord.ui.Button(label="Kupi.cz", url=kupi.BASE, row=0))
    if view == VIEW_MEAT:
        for key, (icon, label) in MEAT_FILTERS.items():
            if key == ALL:
                continue
            current = key == meat_filter
            ui.add_item(SlevyButton(VIEW_MEAT, key, "f", label=label, emoji=icon,
                                    style=style(current), disabled=current, row=1))
    return ui


class Slevy(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.shops = Shops(bot.fetcher)

    async def cog_load(self) -> None:
        self.bot.add_dynamic_items(SlevyButton)
        self.warm_up.start()

    async def cog_unload(self) -> None:
        self.warm_up.cancel()
        self.bot.remove_dynamic_items(SlevyButton)

    @tasks.loop(hours=3)
    async def warm_up(self) -> None:
        """Po startu a pak každé 3 h stáhne data z Kupi.cz na pozadí, ať commandy odpovídají hned."""
        try:
            await self.shops.warm_up()
        except Exception:
            log.exception("Obnova slev z Kupi.cz selhala")

    async def _send(self, interaction: discord.Interaction, view: str) -> None:
        await interaction.response.defer(thinking=True)
        content, embeds, ui = await build_message(self.shops, view)
        await interaction.followup.send(content=content, embeds=embeds, view=ui)

    @app_commands.command(name="slevy", description="🛒 Akční letáky: Lidl, BILLA Srbská, Albert Semilasso, Globus Ivanovice")
    async def slevy(self, interaction: discord.Interaction) -> None:
        await self._send(interaction, VIEW_LEAFLETS)

    @app_commands.command(name="maso", description="🥩 Slevy na maso: Lidl, BILLA Srbská, Albert Semilasso, Globus Ivanovice")
    async def maso(self, interaction: discord.Interaction) -> None:
        await self._send(interaction, VIEW_MEAT)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Slevy(bot))
