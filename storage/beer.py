"""Točená piva v hospodách (/cena-piva). Zadat je může kdokoli, proto se nic nepřepisuje: každá změna (přidání,
úprava, smazání piva, „víc druhů“, vrácení) je nový řádek s celým stavem podniku a aktuální stav = poslední řádek.
Vrátit jde proto na kterýkoli starší stav. Kdo změnu udělal, se ukládá, aby šlo dohledat nesmysly."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime

from pubs.beers import BeerError, PubBeers, Tap, stamp

from .db import Database

HISTORY_LIMIT = 25  # kolik posledních změn ukázat (a nabídnout k vrácení)


@dataclass(frozen=True)
class Version:
    id: int
    pub: str
    state: PubBeers
    change: str
    user_id: int
    created_at: datetime
    reverted_from: int | None = None


_COLUMNS = "id, pub, taps, many_price, change, user_id, created_at, reverted_from"


def _version(row) -> Version:
    created = datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M")
    taps = tuple(
        Tap(t["name"], t["price"], date.fromisoformat(t["since"]) if "since" in t else created.date())
        for t in json.loads(row["taps"])
    )
    state = PubBeers(taps, row["many_price"], f"{created.month}/{created.year}")
    return Version(row["id"], row["pub"], state, row["change"], row["user_id"], created, row["reverted_from"])


async def _latest(conn, pub: str) -> Version | None:
    cursor = await conn.execute(f"SELECT {_COLUMNS} FROM pub_beers WHERE pub = ? ORDER BY id DESC LIMIT 1", (pub,))
    row = await cursor.fetchone()
    return _version(row) if row else None


async def change(
    db: Database, pub: str, edit: Callable[[PubBeers], tuple[PubBeers, str]], user_id: int, now: datetime,
    reverted_from: int | None = None,
) -> Version:
    """Vezme aktuální stav podniku, `edit` z něj udělá nový (a popis změny) a uloží ho. Čtení i zápis jsou v jedné
    transakci, takže se dvě změny naráz nepřepíšou. Chyby z `edit` (pubs.beers.BeerError) projdou ven."""
    async with db.transaction() as tx:
        latest = await _latest(tx, pub)
        state, text = edit(latest.state if latest else PubBeers())
        state = stamp(state, now.date())
        taps = json.dumps(
            [{"name": t.name, "price": t.price, "since": t.since.isoformat()} for t in state.taps], ensure_ascii=False
        )
        cursor = await tx.execute(
            "INSERT INTO pub_beers (pub, taps, many_price, change, user_id, created_at, reverted_from) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pub, taps, state.many_price, text, user_id, now.strftime("%Y-%m-%d %H:%M"), reverted_from),
        )
        new_id = cursor.lastrowid
    created = now.replace(second=0, microsecond=0, tzinfo=None)
    state = replace(state, checked=f"{created.month}/{created.year}")
    return Version(new_id, pub, state, text, user_id, created, reverted_from)


async def revert(db: Database, version: Version, user_id: int, now: datetime) -> Version:
    """Vrátí podnik na starší stav (uloží jeho kopii, historie zůstane celá)."""
    when = f"{version.created_at.day}. {version.created_at.month}. {version.created_at:%H:%M}"

    def back(state: PubBeers) -> tuple[PubBeers, str]:
        if (state.taps, state.many_price) == (version.state.taps, version.state.many_price):
            raise BeerError("Tohle už teď platí.")
        return version.state, f"↩️ vráceno na stav z {when}"

    return await change(db, version.pub, back, user_id, now, reverted_from=version.id)


async def current(db: Database) -> dict[str, PubBeers]:
    """Aktuální stav všech podniků, o kterých něco víme."""
    rows = await db.fetchall(
        f"SELECT {_COLUMNS} FROM pub_beers WHERE id IN (SELECT MAX(id) FROM pub_beers GROUP BY pub)"
    )
    states = {r["pub"]: _version(r).state for r in rows}
    return {pub: s for pub, s in states.items() if not s.empty}


async def history(db: Database, pub: str, limit: int = HISTORY_LIMIT) -> list[Version]:
    """Poslední změny podniku, nejnovější první (první = aktuální stav)."""
    rows = await db.fetchall(f"SELECT {_COLUMNS} FROM pub_beers WHERE pub = ? ORDER BY id DESC LIMIT ?", (pub, limit))
    return [_version(r) for r in rows]


async def get(db: Database, version_id: int) -> Version | None:
    row = await db.fetchone(f"SELECT {_COLUMNS} FROM pub_beers WHERE id = ?", (version_id,))
    return _version(row) if row else None
