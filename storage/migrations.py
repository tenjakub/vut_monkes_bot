"""Schéma databáze jako seznam migrací. Verze schématu = `PRAGMA user_version` = počet provedených migrací.

Pravidla:
- Migrace se jen PŘIDÁVAJÍ na konec. Už vydanou migraci nikdy neměň ani nemaž (na produkci už proběhla).
- Jen přidávat (tabulky, sloupce, indexy), nic nemazat ani nepřejmenovávat. Starší verze bota (návrat přes
  BOT_TAG) pak s novějším schématem pořád funguje: nové tabulky a sloupce prostě nezná.
- Každá migrace běží v jedné transakci i se zvýšením verze: buď proběhne celá, nebo vůbec.
"""

from __future__ import annotations

MIGRATIONS: list[str] = [
    # 1 – statistiky commandů: kolikrát se který command použil v který den. Jen počty, žádná ID lidí.
    """
    CREATE TABLE command_usage (
        day     TEXT    NOT NULL,             -- RRRR-MM-DD (Europe/Prague)
        command TEXT    NOT NULL,             -- název commandu bez lomítka
        count   INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (day, command)
    ) WITHOUT ROWID;
    """,
]

LATEST = len(MIGRATIONS)
