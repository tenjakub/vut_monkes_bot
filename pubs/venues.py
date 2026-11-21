"""Hospody a kluby pro /na-pivo: oblasti (kamkoliv, u PPV, u Purkyní, u FITu, v centru) a podniky v nich.

Nový podnik = jeden řádek v PUBS. Klíč (`key`) se nesmí měnit, jinak by staré zprávy podnik nepoznaly
(podnik se pozná podle názvu v embedu a hodnoty ve výběru). Odkaz na mapu se skládá sám z názvu a adresy;
když Google podnik nenajde správně, dej do `map_url` odkaz z „Sdílet“ v Google Mapách.

Ceny točeného piva (`Pub.beer`) se zadávají ručně a ukazují se, jen když je zapnuté SHOW_BEER_PRICES.
Kde mají hodně druhů, stačí `Beer(70, many=True)` = „víc druhů, kolem 70 Kč“.

Ve výběru „Kam“ jsou nahoře oblasti a pod nimi podniky. Dohromady jich Discord ve výběru unese nejvýš 25.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus


@dataclass(frozen=True)
class Area:
    key: str
    label: str  # "U FITu" – do výběru a nadpisů
    emoji: str
    hint: str = "ještě nevíme kde"  # ve výběru za názvem
    note: str = "kam přesně, se domluví"  # v pozvánce za názvem


# Ceny piva zatím nejsou vyplněné. Po vyplnění `beer` u podniků přepnout na True.
SHOW_BEER_PRICES = False


@dataclass(frozen=True)
class Beer:
    """Točené pivo, cena za 0,5 l v Kč (zadává se ručně)."""

    price: int  # u `many` orientační („kolem“)
    name: str = ""  # jedno pivo: "Plzeň 12°"
    many: bool = False  # víc druhů -> „víc druhů, kolem XX Kč“
    checked: str = ""  # kdy zjištěno, např. "11/2026"

    @property
    def text(self) -> str:
        """'🍻 víc druhů, kolem 70 Kč' / '🍺 Plzeň 12° · 65 Kč' (cena vždy za půllitr)."""
        if self.many:
            text = f"🍻 víc druhů, kolem {self.price} Kč"
        else:
            text = "🍺 " + " · ".join(p for p in (self.name, f"{self.price} Kč") if p)
        return text + (f" ({self.checked})" if self.checked else "")


@dataclass(frozen=True)
class Pub:
    key: str
    name: str
    area: str  # klíč z AREAS
    address: str = ""  # krátce, jen pro lidi ("Jánská 16"); prázdné = neuvádí se
    emoji: str = "🍺"
    query: str = ""  # co hledat v mapě, když název + adresa nestačí
    map_url: str = ""  # vlastní odkaz na mapu (třeba z „Sdílet“ v Google Mapách), má přednost
    beer: Beer | None = None  # cena točeného, např. Beer(65, "Plzeň 12°", checked="11/2026")

    @property
    def beer_text(self) -> str:
        """Cena piva k zobrazení, nebo "" (nevyplněná nebo vypnutá přes SHOW_BEER_PRICES)."""
        return self.beer.text if SHOW_BEER_PRICES and self.beer else ""

    @property
    def map(self) -> str:
        if self.map_url:
            return self.map_url
        query = self.query or ", ".join(p for p in (self.name, self.address, "Brno") if p)
        return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"


AREAS: dict[str, Area] = {
    a.key: a
    for a in [
        Area("kamkoliv", "Kamkoliv", "🎲", "je mi to jedno", "je to jedno, kam se půjde"),
        Area("ppv", "U PPV", "🏘️"),
        Area("purkyne", "U Purkyní", "🏢"),
        Area("fit", "U FITu", "💻"),
        Area("centrum", "V centru", "🏙️"),
    ]
}

PUBS: dict[str, Pub] = {
    p.key: p
    for p in [
        Pub("yacht", "Yacht klub", "ppv", "Kolejní 2 (koleje PPV)", "⛵", query="Kolejní 2, Brno"),
        Pub("purkynka", "Na Purkyňce", "purkyne", "Purkyňova 80"),
        Pub("kachnicka", "U Kachničky", "fit", "Božetěchova 2 (FIT)", "🦆", query="Božetěchova 2, Brno"),
        Pub("mystika", "Mystika", "fit", "Palackého tř. 721", query="Mystika, Brno"),
        Pub("burza", "Pivní burza", "centrum", "Jánská 16"),
        Pub("vlk", "U Dřevěného vlka", "centrum", "Zelný trh", "🐺"),
        Pub("utopie", "Utopie", "centrum", "Divadelní 603", query="Utopie, Brno"),
        Pub("palac", "Pivní palác", "centrum", "Běhounská 18", query="Pivní palác U Vodičků, Brno"),
        Pub("narohu", "Na Rohu", "centrum", "roh Divadelní a Orlí", query="Pivnice Na Rohu, Divadelní, Brno"),
        Pub("krcma", "Rytířská krčma", "centrum", "Lidická 9", "⚔️", query="Rytířská krčma, Brno"),
    ]
}

# Klíče jsou jeden jmenný prostor (hodnoty ve výběru "Kam"), oblast se nesmí jmenovat jako podnik.
assert not AREAS.keys() & PUBS.keys()
assert all(p.area in AREAS for p in PUBS.values())


def pubs_in(area: str) -> list[Pub]:
    return [p for p in PUBS.values() if p.area == area]


def by_name(name: str) -> str | None:
    """Klíč oblasti nebo podniku podle názvu z embedu ("Pivní burza", "V centru")."""
    for key, pub in PUBS.items():
        if pub.name == name:
            return key
    for key, area in AREAS.items():
        if area.label == name:
            return key
    return None
