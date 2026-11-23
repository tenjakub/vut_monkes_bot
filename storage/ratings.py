"""Hodnocení jídel: 👍 dobré / 😐 neurazí / 👎 špatné. Jeden člověk = jedno hodnocení jídla v daný den
(znovu kliknutí ho přepíše, „Zrušit“ smaže). Ukládá se ke konkrétnímu jídlu (`dish.id`), jak bylo na webu.

Souhrn se počítá přes všechny dny, kdy se stejné jídlo vařilo, i s jinou přílohou: jídla se párují podle klíče
bez přílohy, doplňků a gramáže (`lunch.sides.rating_key`), v menzách KaM navíc ze všech menz dohromady
(`lunch.sides.pool`). „Smažený sýr, Hranolky“ v Kolejní tak ukáže i hodnocení „Smažený sýr, tatarská omáčka,
Brambory americké“ z Technické. Klíč se počítá při čtení, takže se dá kdykoli upravit bez změny databáze.

ID uživatele je nutné (aby každý hlasoval jednou a mohl hodnocení zrušit), jinak se nic o lidech neukládá.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from lunch import kam
from lunch.sides import KAM_POOL, pool, rating_key

from .db import Database

GOOD, OK, BAD = 1, 0, -1
SCORES = {GOOD: ("👍", "Dobré"), OK: ("😐", "Neurazí"), BAD: ("👎", "Špatné")}


@dataclass(frozen=True)
class Summary:
    good: int = 0
    ok: int = 0
    bad: int = 0

    def __add__(self, other: Summary) -> Summary:
        return Summary(self.good + other.good, self.ok + other.ok, self.bad + other.bad)

    @property
    def total(self) -> int:
        return self.good + self.ok + self.bad

    def text(self) -> str:
        """„👍 3 · 😐 1“ – jen nenulové počty."""
        parts = [(GOOD, self.good), (OK, self.ok), (BAD, self.bad)]
        return " · ".join(f"{SCORES[s][0]} {n}" for s, n in parts if n)


async def rate(db: Database, dish_id: int, user_id: int, score: int, now: datetime) -> None:
    if score not in SCORES:
        raise ValueError(score)
    await db.execute(
        "INSERT INTO dish_rating (dish_id, user_id, score, rated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (dish_id, user_id) DO UPDATE SET score = excluded.score, rated_at = excluded.rated_at",
        (dish_id, user_id, score, now.strftime("%Y-%m-%d %H:%M")),
    )


async def unrate(db: Database, dish_id: int, user_id: int) -> bool:
    return await db.execute("DELETE FROM dish_rating WHERE dish_id = ? AND user_id = ?", (dish_id, user_id)) > 0


async def scores_of(db: Database, user_id: int, dish_ids: Iterable[int]) -> dict[int, int]:
    """Jak člověk hodnotil daná jídla: {dish_id: score}."""
    ids = list(dish_ids)
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = await db.fetchall(
        f"SELECT dish_id, score FROM dish_rating WHERE user_id = ? AND dish_id IN ({marks})", (user_id, *ids)
    )
    return {r["dish_id"]: r["score"] for r in rows}


def _key(place: str, name: str) -> tuple[str, str]:
    return pool(place), rating_key(name)


async def summaries(db: Database, dishes: Iterable[tuple[str, str]]) -> dict[tuple[str, str], Summary]:
    """Souhrn hodnocení pro (podnik, název jídla): stejné jídlo přes všechny dny, i s jinou přílohou (viz nahoře).
    Jídla bez hodnocení ve výsledku nejsou."""
    wanted = {dish: _key(*dish) for dish in set(dishes)}
    if not wanted:
        return {}
    pools = {p for p, _ in wanted.values()}
    places = sorted({p for p, _ in wanted} | (set(kam.MENZY) if KAM_POOL in pools else set()))
    marks = ",".join("?" * len(places))
    rows = await db.fetchall(
        "SELECT d.place, d.name, "
        "SUM(r.score = 1) AS good, SUM(r.score = 0) AS ok, SUM(r.score = -1) AS bad "
        f"FROM dish_rating r JOIN dish d ON d.id = r.dish_id WHERE d.place IN ({marks}) GROUP BY d.place, d.name",
        places,
    )
    totals: dict[tuple[str, str], Summary] = {}
    for r in rows:
        key = _key(r["place"], r["name"])
        totals[key] = totals.get(key, Summary()) + Summary(r["good"], r["ok"], r["bad"])
    return {dish: totals[key] for dish, key in wanted.items() if key in totals}


async def forget_user(db: Database, user_id: int) -> int:
    """Smaže všechna hodnocení člověka (na požádání)."""
    return await db.execute("DELETE FROM dish_rating WHERE user_id = ?", (user_id,))
