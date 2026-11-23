"""Hodnocení jídel: 👍 dobré / 😐 neurazí / 👎 špatné. Jeden člověk = jedno hodnocení jídla v daný den
(znovu kliknutí ho přepíše, „Zrušit“ smaže). Souhrn se počítá přes všechny dny, kdy se jídlo stejného názvu
v podniku vařilo, takže se hodnocení „přenáší“, když se jídlo zase objeví.

ID uživatele je nutné (aby každý hlasoval jednou a mohl hodnocení zrušit), jinak se nic o lidech neukládá.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from .db import Database

GOOD, OK, BAD = 1, 0, -1
SCORES = {GOOD: ("👍", "Dobré"), OK: ("😐", "Neurazí"), BAD: ("👎", "Špatné")}


@dataclass(frozen=True)
class Summary:
    good: int = 0
    ok: int = 0
    bad: int = 0

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


async def summaries(db: Database, dishes: Iterable[tuple[str, str]]) -> dict[tuple[str, str], Summary]:
    """Souhrn hodnocení podle (podnik, název jídla) přes všechny dny. Jídla bez hodnocení ve výsledku nejsou."""
    wanted = set(dishes)
    if not wanted:
        return {}
    places = sorted({p for p, _ in wanted})
    marks = ",".join("?" * len(places))
    rows = await db.fetchall(
        "SELECT d.place, d.name, "
        "SUM(r.score = 1) AS good, SUM(r.score = 0) AS ok, SUM(r.score = -1) AS bad "
        f"FROM dish_rating r JOIN dish d ON d.id = r.dish_id WHERE d.place IN ({marks}) GROUP BY d.place, d.name",
        places,
    )
    return {
        (r["place"], r["name"]): Summary(r["good"], r["ok"], r["bad"])
        for r in rows if (r["place"], r["name"]) in wanted
    }


async def forget_user(db: Database, user_id: int) -> int:
    """Smaže všechna hodnocení člověka (na požádání)."""
    return await db.execute("DELETE FROM dish_rating WHERE user_id = ?", (user_id,))
