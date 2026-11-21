"""Hospody a kluby pro /na-pivo: oblasti (u PPV, u Purkyní, u FITu, v centru) a podniky v nich.

Nový podnik = jeden řádek v PUBS. Klíč (`key`) se nesmí měnit, jinak by staré zprávy podnik nepoznaly
(podnik se pozná podle názvu v embedu a hodnoty ve výběru). Odkaz na mapu se skládá sám z názvu a adresy;
když Google podnik nenajde správně, dej do `map_url` odkaz z „Sdílet“ v Google Mapách.

Ve výběru „Kam“ jsou oblasti i podniky dohromady a Discord jich ve výběru unese nejvýš 25.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus


@dataclass(frozen=True)
class Area:
    key: str
    label: str  # "U FITu" – do výběru a nadpisů
    emoji: str


@dataclass(frozen=True)
class Pub:
    key: str
    name: str
    area: str  # klíč z AREAS
    address: str = ""  # krátce, jen pro lidi ("Jánská 16"); prázdné = neuvádí se
    emoji: str = "🍺"
    query: str = ""  # co hledat v mapě, když název + adresa nestačí
    map_url: str = ""  # vlastní odkaz na mapu (třeba z „Sdílet“ v Google Mapách), má přednost

    @property
    def map(self) -> str:
        if self.map_url:
            return self.map_url
        query = self.query or ", ".join(p for p in (self.name, self.address, "Brno") if p)
        return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"


AREAS: dict[str, Area] = {
    a.key: a
    for a in [
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
        Pub("mystika", "Mystika", "fit"),
        Pub("burza", "Pivní burza", "centrum", "Jánská 16"),
        Pub("vlk", "U Dřevěného vlka", "centrum", "Zelný trh", "🐺"),
        Pub("utopie", "Utopie", "centrum"),
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
