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
    # 2 – historie jídelníčků (storage/menus.py): polévky a hlavní jídla z menz a restaurací po dnech
    """
    CREATE TABLE dish (
        id         INTEGER PRIMARY KEY,
        day        TEXT    NOT NULL,          -- RRRR-MM-DD
        place      TEXT    NOT NULL,          -- klíč menzy / restaurace (Place.key)
        name       TEXT    NOT NULL,
        category   TEXT    NOT NULL,          -- soup / main
        price_kc   INTEGER,                   -- u menz cena pro studenty VUT
        label      TEXT,                      -- E1, 1, …
        economy    INTEGER NOT NULL DEFAULT 0,
        dish_group TEXT,                      -- Pizza, Těstoviny (Sesamo)
        first_seen TEXT    NOT NULL,          -- HH:MM, kdy se jídlo objevilo
        last_seen  TEXT    NOT NULL,          -- HH:MM, kdy bylo v menu naposledy (menzy vyprodané mažou)
        UNIQUE (day, place, name)
    );
    CREATE INDEX dish_place_name ON dish (place, name);
    """,
]

LATEST = len(MIGRATIONS)
