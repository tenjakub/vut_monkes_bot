"""Práce s textem bez discord.py: čištění toho, co lidi píšou do oken, ceny a české tvary čísel.

`clean`: text od lidí (názvy piv, hlídané věci) se ukazuje ostatním ve zprávách a embedech, takže z něj musí
zmizet všechno, co Discord něčím nahradí: formátování (`**`, `_`, `~`, `|`, `` ` ``, `#`, `>`), odkazy
(`[text](url)`, `https://`), zmínky (`@everyone`, `<@123>`), emoji kódy (`:nazev:`) i konce řádků. Nechávají se
písmena (i s diakritikou), číslice, mezery a pár znaků, které se v názvech hodí. Do databáze jde text vždy přes
parametry (`?`), takže SQL nehrozí.
"""

from __future__ import annotations

import re
import unicodedata

ALLOWED_PUNCTUATION = set(" °.,'’&+/%-()")
_SPACES_RE = re.compile(r"\s+")
_PRICE_RE = re.compile(r"\d+(?:[.,]\d+)?")
_PRICE_INPUT_RE = re.compile(r"^\s*(\d+(?:[.,]\d{1,2})?)\s*(?:kč|,-)?\s*$", re.IGNORECASE)


def clean(text: str, limit: int = 40) -> str:
    """'**Plzeň** 12° @everyone' -> 'Plzeň 12° everyone'. Vrací "", když nic nezbylo."""
    text = unicodedata.normalize("NFC", text)
    kept = "".join(
        c if c in ALLOWED_PUNCTUATION or unicodedata.category(c)[0] in "LN" else " "
        for c in text
    )
    return _SPACES_RE.sub(" ", kept).strip()[:limit].strip()


def price_value(price: str | None) -> float | None:
    """Cena ze zdroje: '159 Kč' -> 159.0, '1 099,90 Kč' -> 1099.9; bez čísla None."""
    m = _PRICE_RE.search((price or "").replace(" ", "").replace(" ", ""))
    return float(m.group().replace(",", ".")) if m else None


def parse_price(text: str) -> float | None:
    """Cena, kterou někdo napsal: '25' / '25,90' / '25 Kč' / '25,-' -> číslo; prázdné -> None; nesmysl -> ValueError."""
    if not text.strip():
        return None
    m = _PRICE_INPUT_RE.match(text)
    if not m or float(m.group(1).replace(",", ".")) <= 0:
        raise ValueError(text)
    return float(m.group(1).replace(",", "."))


def plural(n: int, one: str, few: str, many: str) -> str:
    """'1 kolo', '3 kola', '5 kol' (few = 2–4, many = 0 a 5+)."""
    return f"{n} {one if n == 1 else few if 2 <= n <= 4 else many}"
