"""Stejné jídlo s jinou přílohou: klíč jídla pro hodnocení (⭐) bez přílohy, doplňků a gramáže.

Menzy KaM píšou jídla jako „Hlavní část[, omáčka nebo doplněk], Příloha“ a stejné jídlo bývá jednou s hranolky,
jindy s americkými bramborami nebo bez přílohy:
    „Smažený sýr, tatarská omáčka, Brambory americké“ = „Smažený sýr, tatarská omáčka“ = „Smažený sýr, Hranolky“
    „Vepřový steak 200g, omáčka tatarská, Hranolky“ = „Vepřový steak 150g“
Restaurace mají přílohu většinou taky za čárkou („…, houskový knedlík“, „…, vařené brambory s petrželkou“).

Klíč = první část názvu (bez „s hranolky“ na konci) + další části za čárkou, které nejsou příloha ani doplněk,
malými písmeny, bez gramáže, závorek a interpunkce. Části, které jídlo tvoří („pepřová omáčka“, „slaninový
chips“, „dušené zelí na slanině“), v klíči zůstávají. Příloha se pozná podle slov (`SIDE_STEMS`), doplněk podle
`EXTRA_STEMS`. Hodnocení se pak sčítají podle klíče, v menzách KaM navíc dohromady (`pool`), protože vaří podle
stejných receptů a jídla se jmenují všude stejně.
"""

from __future__ import annotations

import re

from . import kam

# začátky slov, podle kterých se pozná příloha („Brambory americké“, „dušená rýže“, „houskový knedlík“)
SIDE_STEMS = (
    "hranol", "brambor", "kaše", "kaši", "rýž", "knedl", "těstovin", "halušk", "kuskus", "bulgur", "kroket",
    "noky", "špecl", "chléb", "chleb", "pečiv", "bagetk", "pyré", "batát", "jáhl", "quinoa",
)
# doplňky, které na jídle nic nemění (tatarská omáčka, okurek, dresink, obloha)
EXTRA_STEMS = ("tatar", "kečup", "hořčic", "okur", "dresink", "dressing", "dip", "salátek", "obloh")
KAM_POOL = "kam"

_PARENS_RE = re.compile(r"\([^()]*\)")
_WEIGHT_RE = re.compile(r"\b\d+\s*(?:g|kg|ks|ml|l)\b")
_WITH_RE = re.compile(r"\s(?:s|se)\s")  # „Kuřecí řízek s bramborovým salátem“
_NON_WORD_RE = re.compile(r"[^\w]+")


def _words(text: str) -> list[str]:
    return [w for w in _NON_WORD_RE.split(text.casefold().replace("_", " ")) if w]


def _has(words: list[str], stems: tuple[str, ...]) -> bool:
    return any(w.startswith(stems) for w in words)


def _split_top(name: str) -> list[str]:
    """Části za čárkou, ale ne čárky v závorkách („Burger (maso, cibule), hranolky“)."""
    parts, depth, start = [], 0, 0
    for i, c in enumerate(name):
        depth += (c == "(") - (c == ")")
        if c == "," and depth <= 0:
            parts.append(name[start:i])
            start = i + 1
    return [p.strip() for p in parts + [name[start:]] if p.strip()]


def rating_key(name: str) -> str:
    """'Smažený sýr, tatarská omáčka, Hranolky' -> 'smažený sýr'. Když by nic nezbylo, celý název."""
    parts = _split_top(_WEIGHT_RE.sub(" ", _PARENS_RE.sub(" ", name)))
    if not parts:
        return " ".join(_words(name))
    first = parts[0]
    withs = list(_WITH_RE.finditer(first))
    if withs and _has(_words(first[withs[-1].end():]), SIDE_STEMS):  # „… s bramborovým salátem“ = příloha
        first = first[: withs[-1].start()].strip() or first
    kept = [first] + [p for p in parts[1:] if not _has(_words(p), SIDE_STEMS + EXTRA_STEMS)]
    return " ".join(w for p in kept for w in _words(p)) or " ".join(_words(name))


def pool(place: str) -> str:
    """Kde se hodnocení sčítají: všechny menzy KaM dohromady, restaurace každá zvlášť."""
    return KAM_POOL if place in kam.MENZY else place
