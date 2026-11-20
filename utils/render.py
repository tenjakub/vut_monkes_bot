"""Převod jídelníčků (lunch.models.Menu) na Discord embedy.

Každé jídlo je samostatný field embedu ("kartička"): v nadpisu emoji, štítek a cena,
pod tím název. Inline fieldy Discord na desktopu skládá do mřížky po třech,
na mobilu pod sebe.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

import discord

from lunch import emoji
from lunch.models import Dish, Menu
from lunch.service import today

# Discord limity: 10 embedů na zprávu, 6000 znaků dohromady, 25 fieldů na embed
MAX_EMBEDS = 10
MAX_FIELDS = 25
GRID_COLUMNS = 3
BLANK = "\u200b"  # zero-width space – prázdný field
TOTAL_BUDGET = 5800
FIELD_VALUE_LIMIT = 1024

WEEKDAYS = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]


def czech_date(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day}. {d.month}."


@dataclass
class Field:
    name: str
    value: str
    inline: bool = True

    def __len__(self) -> int:
        return len(self.name) + len(self.value)


def _split_caps_title(name: str) -> tuple[str | None, str]:
    """'CHICKEN MADRAS Kuřecí kostky…' -> ('Chicken Madras', 'Kuřecí kostky…').

    Některé restaurace (Padagali) píšou název jídla velkými písmeny a za ním popis.
    """
    words = name.split()
    n = 0
    for w in words:
        letters = "".join(c for c in w if c.isalpha())
        if len(letters) < 2 or not letters.isupper():
            break
        n += 1
    caps = "".join(words[:n])
    if n == 0 or n == len(words) or sum(c.isalpha() for c in caps) < 4:
        return None, name
    return " ".join(words[:n]).title(), " ".join(words[n:])


def dish_field(d: Dish, inline: bool = True) -> Field:
    head = " · ".join(p for p in (d.label, d.price) if p)
    title, rest = _split_caps_title(d.name)
    value = f"**{title}**\n{rest}" if title else d.name
    return Field(f"{emoji.for_dish(d)} {head}".strip(), value[:FIELD_VALUE_LIMIT], inline)


def _soup_name(name: str) -> str:
    """'Polévka rajčatová s těstovinou' -> 'Rajčatová s těstovinou' (nadpis už říká Polévka)."""
    title, rest = _split_caps_title(name)
    if title:
        name = f"{title} {rest}"
    short = re.sub(r"^polévka\s+", "", name, flags=re.IGNORECASE)
    return short[:1].upper() + short[1:] if short else name


def soup_field(soups: list[Dish]) -> list[Field]:
    if not soups:
        return []
    lines = [_soup_name(d.name) + (f" — {d.price}" if d.price else "") for d in soups]
    title = "Polévka" if len(soups) == 1 else "Polévky"
    return [Field(f"{emoji.SOUP} {title}", "\n".join(lines)[:FIELD_VALUE_LIMIT], inline=False)]


def per_embed_limit(count: int) -> int:
    count = max(1, min(count, MAX_EMBEDS))
    # ~120 znaků rezerva na titulek a patičku každého embedu
    return TOTAL_BUDGET // count - 120


def add_fields(embed: discord.Embed, fields: list[Field], limit: int) -> None:
    """Přidá fieldy a každou řadu inline kartiček doplní prázdnými do násobku GRID_COLUMNS.

    Bez toho Discord roztáhne osamocenou kartičku v poslední řadě přes celou šířku
    a vypadá pak jako další nadpis.
    """
    run = 0  # počet inline fieldů v aktuální řadě

    def close_row() -> None:
        nonlocal run
        while run % GRID_COLUMNS:
            embed.add_field(name=BLANK, value=BLANK, inline=True)
            run += 1
        run = 0

    used = 0
    for i, f in enumerate(fields):
        # rezerva na doplnění řady (2) + poznámku o zbytku (1)
        if used + len(f) + 60 > limit or len(embed.fields) + 1 + GRID_COLUMNS > MAX_FIELDS:
            close_row()
            embed.add_field(name="…", value=f"a dalších {len(fields) - i} – viz web", inline=False)
            return
        if not f.inline:
            close_row()
        embed.add_field(name=f.name, value=f.value, inline=f.inline)
        used += len(f)
        if f.inline:
            run += 1
    close_row()


def menu_embed(menu: Menu, fields: list[Field], limit: int, empty_text: str) -> discord.Embed:
    place = menu.place
    embed = discord.Embed(title=f"{place.emoji} {place.name}", url=place.url, color=place.color)
    if menu.hours:
        embed.set_footer(text=f"Menu: {menu.hours}")

    if menu.error:
        embed.description = f"⚠️ {menu.error}"
    elif not fields:
        embed.description = f"ℹ️ {menu.note}" if menu.note else f"_{empty_text}_"
    else:
        add_fields(embed, fields, limit)
    return embed


def header(title: str, menus: list[Menu], extra: str | None = None) -> str:
    """Hlavička zprávy: nadpis s datem a pod ním, kdy byla data stažena.

    <t:…:t> a <t:…:R> jsou Discord timestampy – každý je vidí ve svém čase
    a relativní "před 5 minutami" se v klientu samo průběžně aktualizuje.
    """
    lines = [f"### {title} – {czech_date(today())}"]
    info = []
    times = [m.fetched_at for m in menus if m.fetched_at]
    if times:
        ts = int(min(times).timestamp())
        info.append(f"🕒 Aktualizováno <t:{ts}:t> (<t:{ts}:R>)")
    if extra:
        info.append(extra)
    if info:
        lines.append(" · ".join(info))
    return "\n".join(lines)
