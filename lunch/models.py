"""Společné datové struktury pro jídelníčky."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

_WS_RE = re.compile(r"\s+")


def norm(text: str | None) -> str:
    """Sjednotí bílé znaky (včetně &nbsp;) a ořízne okraje."""
    if not text:
        return ""
    return _WS_RE.sub(" ", text.replace("\xa0", " ")).strip()


class Category(Enum):
    SOUP = "soup"
    MAIN = "main"
    SIDE = "side"  # saláty, přílohy, dezerty… (u menz "O: Ostatní")


# Jednotná hláška všech restaurací, když na dnešek menu není (stejná jako na menicka.cz).
NO_MENU = "Pro tento den nebylo zadáno menu."


@dataclass(frozen=True)
class Place:
    """Jedno místo, kde se dá najíst (menza / restaurace)."""

    key: str
    name: str
    url: str  # odkaz pro lidi (do embedu)
    emoji: str = "🍽️"
    color: int = 0x5865F2


@dataclass
class Dish:
    name: str
    price: str | None = None
    category: Category = Category.MAIN
    label: str | None = None  # např. "E1" u Economy, "1" u restaurací
    economy: bool = False
    # na výběr v rámci jednoho menu (pizza dne v La Stradě): (název, popis)
    options: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Menu:
    place: Place
    dishes: list[Dish] = field(default_factory=list)
    note: str | None = None  # info pro uživatele (zavřeno, svátek, …)
    error: str | None = None  # nepodařilo se stáhnout / naparsovat
    hours: str | None = None  # výdejní/otevírací doba, pokud ji zdroj uvádí
    hours_label: str = "Menu:"  # co se v patičce napíše před hours
    fetched_at: datetime | None = None

    @property
    def soups(self) -> list[Dish]:
        return [d for d in self.dishes if d.category is Category.SOUP]

    @property
    def mains(self) -> list[Dish]:
        return [d for d in self.dishes if d.category is Category.MAIN]

    @property
    def economy(self) -> list[Dish]:
        return [d for d in self.dishes if d.economy]
