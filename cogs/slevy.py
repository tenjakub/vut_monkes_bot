"""/letaky, /maso, /napoje a /pivo – akční letáky a vybrané slevy supermarketů, data z Kupi.cz."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from lunch import emoji
from lunch.service import today
from shops import kupi
from shops.service import (
    BEER_CATEGORIES,
    BEER_PACK,
    BEER_PACKS,
    DRINK_CATEGORIES,
    MEAT_CATEGORIES,
    STORES,
    SUGAR_FREE,
    Shops,
    Store,
    beer_pack,
    price_per_liter,
    sugar_free,
)
from utils import render

log = logging.getLogger(__name__)

VIEW_LEAFLETS = "letaky"
VIEW_MEAT = "maso"
VIEW_DRINKS = "napoje"
VIEW_BEER = "pivo"
ALL = "vse"
MAX_DEALS = 10  # akcí na obchod
MAX_LEAFLETS = 5
SHORT_DAYS = ["po", "út", "st", "čt", "pá", "so", "ne"]


@dataclass(frozen=True)
class DealView:
    """Výpis akcí z vybraných kategorií Kupi.cz (maso, nápoje, pivo)."""

    key: str
    title: str
    button: tuple[str, str]  # (emoji, popisek) tlačítka v horní řadě
    categories: dict[str, tuple[str, str]]  # kategorie Kupi.cz, ze kterých se akce berou
    filters: dict[str, tuple[str, str]]  # tlačítka filtru: klíč -> (emoji, popisek)
    classify: Callable[[kupi.Deal], str | None]  # akce -> klíč filtru, None = nezobrazovat
    loader: str  # metoda Shops, která akce stáhne
    empty: str
    link_category: str  # kategorie Kupi.cz pro odkaz "všechny akce řetězce"
    note: str = ""  # vysvětlivka pod nadpisem zprávy


DEAL_VIEWS: dict[str, DealView] = {
    v.key: v
    for v in [
        DealView(
            VIEW_MEAT, "🥩 Slevy na maso", ("🥩", "Maso"), MEAT_CATEGORIES,
            {k: MEAT_CATEGORIES[k] for k in ("veprove-maso", "hovezi-maso", "drubez")},
            lambda d: d.category, "meat_deals",
            "Teď tu žádné slevy na maso nejsou.", "maso-drubez-a-ryby",
        ),
        DealView(
            VIEW_DRINKS, "🥤 Nápoje bez cukru", ("🥤", "Nápoje"), DRINK_CATEGORIES, DRINK_CATEGORIES,
            lambda d: d.category if sugar_free(d) else None, "drink_deals",
            "Teď tu žádné nápoje bez cukru v akci nejsou.", "nealko-napoje",
            "✅ výslovně bez cukru · 🤷 akce na různé druhy značky, která má i verzi bez cukru",
        ),
        DealView(
            VIEW_BEER, "🍺 Pivo v akci", ("🍺", "Pivo"), BEER_CATEGORIES, BEER_PACKS,
            beer_pack, "beer_deals",
            "Teď tu žádné pivo v akci není. 😢", "pivo",
            "🍾 lahve · 🥫 plechovky · 📦 basy a multipacky (s cenou za litr) · bez PET lahví, sudů a dárkových balení",
        ),
    ]
}
VIEWS = (VIEW_LEAFLETS, *DEAL_VIEWS)
# zpětná kompatibilita (testy, starší kód)
MEAT_FILTERS = {ALL: ("🥩", "Všechno"), **DEAL_VIEWS[VIEW_MEAT].filters}

_DRINK_PREFIX_RE = re.compile(r"^(energetický nápoj|limonád[ay])\s+", re.IGNORECASE)
_BEER_PREFIX_RE = re.compile(r"^pivo\s+", re.IGNORECASE)


def _pretty_amount(amount: str) -> str:
    """'6x 0.5 l' -> '6× 0,5 l'"""
    return re.sub(r"(\d)\.(\d)", r"\1,\2", re.sub(r"(\d)\s*x\s*", r"\1× ", amount))


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


# --- akce (maso, nápoje) ----------------------------------------------------------------------


def _deal_line(d: kupi.Deal, view: DealView, day: date) -> str:
    extra = ""
    if view.key == VIEW_DRINKS:
        icon = view.categories.get(d.category, ("🥤",))[0]
        name = _DRINK_PREFIX_RE.sub("", d.product) or d.product
    elif view.key == VIEW_BEER:
        pack = beer_pack(d)
        icon = BEER_PACKS.get(pack, ("🍺",))[0]
        name = _BEER_PREFIX_RE.sub("", d.product) or d.product
        per_liter = price_per_liter(d)
        if pack == BEER_PACK and per_liter:
            extra = f" ({per_liter:.0f} Kč/l)"
    else:
        icon = emoji.for_name(d.product)
        if icon == emoji.FALLBACK:
            icon = view.categories.get(d.category, ("🥩",))[0]
        name = d.product
    name = name[:1].upper() + name[1:]
    name = name if len(name) <= 55 else name[:54] + "…"
    amount = f" {_pretty_amount(d.amount)}" if d.amount else ""
    pct = f" `−{d.percent} %`" if d.percent else ""
    when = _validity(d.valid_from, d.valid_to, day)
    return f"{icon} {name}{amount} — **{d.price}**{extra}{pct}" + (f" · {when}" if when else "")


def store_deals(
    deals: list[kupi.Deal],
    store: Store,
    flt: str,
    day: date,
    view: str = VIEW_MEAT,
    only_discount: bool = False,
) -> list[kupi.Deal]:
    """Akce obchodu: (u nápojů nejdřív jistě bez cukru,) pak platné teď podle slevy a ceny za jednotku,
    nakonec budoucí."""
    classify = DEAL_VIEWS[view].classify
    mine = []
    for d in deals:
        kind = classify(d)
        if (
            kind is not None
            and d.shop in store.shop_labels
            and (flt == ALL or kind == flt)
            and not (d.valid_to and d.valid_to < day)
            and (not only_discount or d.percent)
        ):
            mine.append(d)

    def key(d: kupi.Deal):
        sure = view != VIEW_DRINKS or sugar_free(d) == SUGAR_FREE
        unit = price_per_liter(d) or 0.0
        return (not sure, not d.is_current(day), -(d.percent or 0), unit, d.product)

    return sorted(mine, key=key)


def _deals_embed(
    store: Store, view: DealView, deals: list[kupi.Deal], flt: str, only_discount: bool, day: date, limit: int, error: bool
) -> discord.Embed:
    icon, label = view.filters.get(flt, view.button)
    title = f"{icon} {store.name}" + ("" if flt == ALL else f" · {label}")
    embed = discord.Embed(
        title=title,
        url=f"{kupi.BASE}/slevy/{view.link_category}/{store.kupi_chain}",  # unikátní pro každý obchod
        color=store.color,
    )
    mine = store_deals(deals, store, flt, day, view.key, only_discount)[:MAX_DEALS * 2]
    if not mine:
        if error:
            embed.description = "⚠️ Slevy se nepodařilo načíst."
        elif only_discount:
            embed.description = "_Teď tu nic se slevou v % není._"
        else:
            embed.description = f"_{view.empty}_"
        return embed

    if view.key == VIEW_DRINKS:
        sure = [d for d in mine if sugar_free(d) == SUGAR_FREE]
        maybe = [d for d in mine if sugar_free(d) != SUGAR_FREE]
        lines = []
        if sure:
            lines += ["**✅ Bez cukru**"] + [_deal_line(d, view, day) for d in sure]
        if maybe:
            lines += ["**🤷 Různé druhy (můžou být i bez cukru)**"] + [_deal_line(d, view, day) for d in maybe]
        lines = lines[: MAX_DEALS + 2]
    else:
        lines = [_deal_line(d, view, day) for d in mine[:MAX_DEALS]]
    shown = sum(1 for l in lines if not l.startswith("**"))
    text = _fit(lines, limit, "_…a další ({n}) na Kupi.cz_")
    if len(mine) > shown and "a další" not in text:
        text += f"\n_…a další ({len(mine) - shown}) na Kupi.cz_"
    embed.description = text
    return embed


# --- zpráva a tlačítka ------------------------------------------------------------------------


async def build_message(
    shops: Shops, view: str, flt: str = ALL, force: bool = False, only_discount: bool = False
) -> tuple[str, list[discord.Embed], discord.ui.View]:
    day = today()
    stores = list(STORES.values())
    info = "Data z [Kupi.cz](https://www.kupi.cz)"
    if view in DEAL_VIEWS:
        dv = DEAL_VIEWS[view]
        result = await getattr(shops, dv.loader)(force=force)
        limit = render.per_embed_limit(len(stores))
        embeds = [
            _deals_embed(s, dv, result.deals, flt, only_discount, day, limit, bool(result.errors)) for s in stores
        ]
        title = dv.title + (" · jen se slevou" if only_discount else "")
        if result.fetched_at:
            info += f" · aktualizováno <t:{int(result.fetched_at)}:R>"
        if dv.note:
            info += f"\n-# {dv.note}"
    else:
        pages = await shops.store_pages(force=force)
        embeds = [_leaflets_embed(s, pages, day) for s in stores]
        title = "📰 Akční letáky"
    content = f"### {title} – {render.czech_date(day)}\n{info}"
    return content, embeds, build_view(view, flt, only_discount)


class SlevyButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"slevy:(?P<view>[a-z]+):(?P<filter>[a-z-]+)(?::(?P<only>[01]))?:(?P<slot>[gfor])",
):
    """Stav je v custom_id: pohled, filtr kategorie, jen se slevou (0/1; starší tlačítka ho nemají).

    slot: g = přepnutí pohledu, f = filtr kategorie, o = přepínač "jen se slevou", r = obnovit
    """

    def __init__(self, view: str, flt: str, only: bool, slot: str, **button_kwargs) -> None:
        super().__init__(discord.ui.Button(custom_id=f"slevy:{view}:{flt}:{int(only)}:{slot}", **button_kwargs))
        self.view_name = view
        self.flt = flt
        self.only = only
        self.slot = slot

    @classmethod
    async def from_custom_id(
        cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /
    ) -> SlevyButton:
        return cls(match["view"], match["filter"], match["only"] == "1", match["slot"])

    async def callback(self, interaction: discord.Interaction) -> None:
        valid_filters = {ALL, *(DEAL_VIEWS[self.view_name].filters if self.view_name in DEAL_VIEWS else ())}
        if self.view_name not in VIEWS or self.flt not in valid_filters:
            await interaction.response.send_message("Tohle tlačítko už je zastaralé.", ephemeral=True)
            return
        await interaction.response.defer()
        cog = interaction.client.get_cog("Slevy")  # type: ignore[attr-defined]
        content, embeds, view = await build_message(
            cog.shops, self.view_name, self.flt, force=self.slot == "r", only_discount=self.only
        )
        await interaction.edit_original_response(content=content, embeds=embeds, view=view)


def build_view(view: str, flt: str = ALL, only_discount: bool = False) -> discord.ui.View:
    ui = discord.ui.View(timeout=None)

    def style(current: bool) -> discord.ButtonStyle:
        return discord.ButtonStyle.primary if current else discord.ButtonStyle.secondary

    # 1. řada: letáky / maso / nápoje / pivo, obnovit (max 5 tlačítek v řadě)
    current = view == VIEW_LEAFLETS
    ui.add_item(SlevyButton(VIEW_LEAFLETS, ALL, False, "g", label="Letáky", emoji="📰",
                            style=style(current), disabled=current, row=0))
    for dv in DEAL_VIEWS.values():
        current = view == dv.key and flt == ALL
        ui.add_item(SlevyButton(dv.key, ALL, only_discount, "g", label=dv.button[1], emoji=dv.button[0],
                                style=style(current), disabled=current, row=0))
    ui.add_item(SlevyButton(view, flt, only_discount, "r", label="Obnovit", emoji="🔄",
                            style=discord.ButtonStyle.secondary, row=0))

    # 2. řada: (u akcí) filtry a přepínač "jen se slevou", odkaz na Kupi.cz
    if view in DEAL_VIEWS:
        dv = DEAL_VIEWS[view]
        for key, (icon, label) in dv.filters.items():
            current = key == flt
            ui.add_item(SlevyButton(view, key, only_discount, "f", label=label, emoji=icon,
                                    style=style(current), disabled=current, row=1))
        ui.add_item(SlevyButton(view, flt, not only_discount, "o", label="Jen se slevou", emoji="🏷️",
                                style=discord.ButtonStyle.success if only_discount else discord.ButtonStyle.secondary,
                                row=1))
    ui.add_item(discord.ui.Button(label="Kupi.cz", url=kupi.BASE, row=1))
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

    @app_commands.command(name="letaky", description="📰 Akční letáky: Lidl, BILLA Srbská, Albert Semilasso, Globus Ivanovice")
    async def letaky(self, interaction: discord.Interaction) -> None:
        await self._send(interaction, VIEW_LEAFLETS)

    @app_commands.command(name="maso", description="🥩 Slevy na maso: Lidl, BILLA Srbská, Albert Semilasso, Globus Ivanovice")
    async def maso(self, interaction: discord.Interaction) -> None:
        await self._send(interaction, VIEW_MEAT)

    @app_commands.command(name="pivo", description="🍺 Pivo v akci – lahve, plechovky, basy: Lidl, BILLA, Albert, Globus")
    async def pivo(self, interaction: discord.Interaction) -> None:
        await self._send(interaction, VIEW_BEER)

    @app_commands.command(name="napoje", description="🥤 Energetické nápoje a limonády bez cukru v akci (Lidl, BILLA, Albert, Globus)")
    async def napoje(self, interaction: discord.Interaction) -> None:
        await self._send(interaction, VIEW_DRINKS)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Slevy(bot))
