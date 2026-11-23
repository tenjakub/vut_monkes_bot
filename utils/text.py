"""Čištění textu, který lidi píšou do oken (názvy piv, hlídané věci). Bez discord.py.

Text se pak ukazuje ostatním ve zprávách a embedech, takže z něj musí zmizet všechno, co Discord něčím nahradí:
formátování (`**`, `_`, `~`, `|`, `` ` ``, `#`, `>`), odkazy (`[text](url)`, `https://`), zmínky (`@everyone`,
`<@123>`), emoji kódy (`:nazev:`) i konce řádků. Nechávají se písmena (i s diakritikou), číslice, mezery a pár
znaků, které se v názvech hodí. Do databáze jde text vždy přes parametry (`?`), takže SQL nehrozí.
"""

from __future__ import annotations

import re
import unicodedata

ALLOWED_PUNCTUATION = set(" °.,'’&+/%-()")
_SPACES_RE = re.compile(r"\s+")


def clean(text: str, limit: int = 40) -> str:
    """'**Plzeň** 12° @everyone' -> 'Plzeň 12° everyone'. Vrací "", když nic nezbylo."""
    text = unicodedata.normalize("NFC", text)
    kept = "".join(
        c if c in ALLOWED_PUNCTUATION or unicodedata.category(c)[0] in "LN" else " "
        for c in text
    )
    return _SPACES_RE.sub(" ", kept).strip()[:limit].strip()
