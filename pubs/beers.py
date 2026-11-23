"""Točená piva v hospodě: seznam piv s cenou za 0,5 l, nebo ručně „víc druhů, ~XX Kč“ (Pivní burza).
Bez discord.py a databáze. Změny se dělají funkcemi `add`, `remove`, `set_many`, které vrátí nový stav a popis
změny do historie (`storage/beer.py` ukládá každý stav zvlášť, takže jde vrátit jakýkoli starší).

Jak se to ukazuje ve výpisech (`text`, krátce `price_text`):
- 1–2 piva: „💰 Plzeň 12° · 59 Kč, Kozel 11° · 45 Kč“ (krátce „59 Kč“ / „45–59 Kč“),
- 3 a víc: „💰 4 piva · ~55 Kč“ (medián cen),
- ručně víc druhů: „💰 víc druhů · ~70 Kč“ (má přednost před seznamem).
💰 a ne 🍺, protože pivo je ikona některých podniků.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, replace

MIN_PRICE, MAX_PRICE = 10, 500  # Kč za 0,5 l, víc nebo míň je skoro jistě překlep
MAX_TAPS = 15  # piv v jedné hospodě (výběr v Discordu unese 25)
SHOW_ALL = 2  # do kolika piv se vypisují jednotlivě, víc = medián


class BeerError(ValueError):
    """Změnu nejde udělat, text je hláška pro uživatele."""


@dataclass(frozen=True)
class Tap:
    name: str
    price: int

    @property
    def text(self) -> str:
        return f"{self.name} · {self.price} Kč"


def _key(name: str) -> str:
    return name.casefold()


def _beers(n: int) -> str:
    return f"{n} piva" if 2 <= n <= 4 else f"{n} piv"


@dataclass(frozen=True)
class PubBeers:
    taps: tuple[Tap, ...] = ()  # seřazené podle ceny
    many_price: int | None = None  # ručně „víc druhů, ~XX Kč“
    checked: str = ""  # kdy naposledy změněno („11/2026“)

    @property
    def empty(self) -> bool:
        return not self.taps and self.many_price is None

    @property
    def price_text(self) -> str:
        """Jen cena: „59 Kč“, „45–59 Kč“, „~55 Kč“; "" když nic nevíme."""
        if self.many_price is not None:
            return f"~{self.many_price} Kč"
        prices = [t.price for t in self.taps]
        if not prices:
            return ""
        if len(prices) > SHOW_ALL:
            return f"~{round(statistics.median(prices))} Kč"
        low, high = min(prices), max(prices)
        return f"{low} Kč" if low == high else f"{low}–{high} Kč"

    @property
    def summary(self) -> str:
        """Bez emoji a data: „Plzeň 12° · 59 Kč“, „4 piva · ~55 Kč“, „víc druhů · ~70 Kč“."""
        if self.many_price is not None:
            return f"víc druhů · {self.price_text}"
        if len(self.taps) > SHOW_ALL:
            return f"{_beers(len(self.taps))} · {self.price_text}"
        return ", ".join(t.text for t in self.taps)

    @property
    def text(self) -> str:
        """Řádek do /na-pivo a Kde co je, "" když nic nevíme."""
        if self.empty:
            return ""
        return f"💰 {self.summary}" + (f" ({self.checked})" if self.checked else "")

    def find(self, name: str) -> Tap | None:
        return next((t for t in self.taps if _key(t.name) == _key(name)), None)


def _with_taps(state: PubBeers, taps: list[Tap]) -> PubBeers:
    return replace(state, taps=tuple(sorted(taps, key=lambda t: (t.price, _key(t.name)))))


def add(state: PubBeers, name: str, price: int, original: str | None = None) -> tuple[PubBeers, str]:
    """Přidá pivo, nebo upraví existující (`original` = jak se jmenovalo, když se přejmenovává)."""
    old = state.find(original) if original else None
    if original and old is None:
        raise BeerError(f"Pivo „{original}“ už v seznamu není, někdo ho mezitím změnil.")
    clash = state.find(name)
    if clash is not None and clash is not old:
        raise BeerError(f"Pivo „{clash.name}“ už v seznamu je, uprav ho ve výběru ✏️.")
    if old is None and len(state.taps) >= MAX_TAPS:
        raise BeerError(f"Víc než {MAX_TAPS} piv se nevejde. Na velký výběr je 🍻 Víc druhů.")
    new = Tap(name, price)
    if old == new:
        raise BeerError("Nic se nezměnilo.")
    taps = [t for t in state.taps if t is not old] + [new]
    if old is None:
        change = f"➕ {new.text}"
    elif old.name != new.name:
        change = f"✏️ {old.name} → {new.text}"
    else:
        change = f"✏️ {new.name} · {old.price} → {new.price} Kč"
    return _with_taps(state, taps), change


def remove(state: PubBeers, name: str) -> tuple[PubBeers, str]:
    old = state.find(name)
    if old is None:
        raise BeerError(f"Pivo „{name}“ už v seznamu není, někdo ho mezitím změnil.")
    return _with_taps(state, [t for t in state.taps if t is not old]), f"🗑️ {old.name}"


def set_many(state: PubBeers, price: int | None) -> tuple[PubBeers, str]:
    """Ručně „víc druhů, ~XX Kč“, `None` ho zruší (zase se ukazuje seznam piv)."""
    if price == state.many_price:
        raise BeerError("Nic se nezměnilo.")
    change = f"🍻 víc druhů · ~{price} Kč" if price is not None else "🍻 zrušeno „víc druhů“"
    return replace(state, many_price=price), change


def parse_price(text: str, required: bool = True) -> int | None:
    """'59' / '59 Kč' / '59,-' -> 59; prázdné -> None (když nepovinné); nesmysl -> BeerError."""
    raw = text.strip().lower().removesuffix("kč").removesuffix(",-").strip()
    if not raw:
        if required:
            raise BeerError("Chybí cena.")
        return None
    if not raw.isdigit() or not MIN_PRICE <= int(raw) <= MAX_PRICE:
        raise BeerError(f"Cenu „{text.strip()}“ nechápu 🤔 Napiš celé číslo v Kč za půllitr ({MIN_PRICE}–{MAX_PRICE}).")
    return int(raw)
