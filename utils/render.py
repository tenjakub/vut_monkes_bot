"""Převod jídelníčků (lunch.models.Menu) na Discord embedy."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date

import discord

from lunch.models import Dish, Menu

# Discord limity: 10 embedů na zprávu, 6000 znaků dohromady, 4096 na description
MAX_EMBEDS = 10
TOTAL_BUDGET = 5800
DESC_LIMIT = 4096

WEEKDAYS = ["pondělí", "úterý", "středa", "čtvrtek", "pátek", "sobota", "neděle"]


def czech_date(d: date) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day}. {d.month}."


def dish_line(d: Dish) -> str:
    label = f"`{d.label}` " if d.label else ""
    price = f" — **{d.price}**" if d.price else ""
    return f"{label}{d.name}{price}"


def soup_line(d: Dish) -> str:
    price = f" — {d.price}" if d.price else ""
    return f"🥣 {d.name}{price}"


def section(title: str | None, lines: Iterable[str]) -> list[str]:
    lines = list(lines)
    if not lines:
        return []
    return ([f"**{title}**"] if title else []) + lines


def fit_lines(lines: list[str], limit: int) -> str:
    """Poskládá řádky do limitu znaků; co se nevejde, nahradí poznámkou."""
    out: list[str] = []
    used = 0
    for i, line in enumerate(lines):
        rest = len(lines) - i
        reserve = 40 if rest > 1 else 0  # místo na "…a další"
        if used + len(line) + 1 + reserve > limit:
            hidden = sum(1 for x in lines[i:] if not x.startswith("**"))
            out.append(f"_…a dalších {hidden} položek – viz web_")
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


def menu_embed(menu: Menu, lines: list[str], limit: int, empty_text: str) -> discord.Embed:
    place = menu.place
    if menu.error:
        description = f"⚠️ {menu.error}"
    elif menu.note and not lines:
        description = f"ℹ️ {menu.note}"
    elif not lines:
        description = f"_{empty_text}_"
    else:
        description = fit_lines(lines, limit)

    embed = discord.Embed(
        title=f"{place.emoji} {place.name}",
        url=place.url,
        description=description,
        color=place.color,
    )
    if menu.hours:
        embed.set_footer(text=f"Menu: {menu.hours}")
    return embed


def per_embed_limit(count: int) -> int:
    count = max(1, min(count, MAX_EMBEDS))
    # ~120 znaků rezerva na titulek a patičku každého embedu
    return min(DESC_LIMIT, TOTAL_BUDGET // count - 120)


def finish(embeds: list[discord.Embed], footer: str, menus: list[Menu]) -> list[discord.Embed]:
    """Na poslední embed dá společnou patičku a čas stažení dat."""
    if not embeds:
        return embeds
    last = embeds[-1]
    text = footer
    if last.footer and last.footer.text:
        text = f"{last.footer.text} · {footer}"
    last.set_footer(text=text)
    times = [m.fetched_at for m in menus if m.fetched_at]
    if times:
        last.timestamp = min(times)
    return embeds
