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
    # 3 – hodnocení jídel (storage/ratings.py): každý jedno hodnocení na jídlo, dá se zrušit
    """
    CREATE TABLE dish_rating (
        dish_id  INTEGER NOT NULL REFERENCES dish (id) ON DELETE CASCADE,
        user_id  INTEGER NOT NULL,            -- Discord ID (jedno hodnocení na člověka, zrušit ho může jen on)
        score    INTEGER NOT NULL CHECK (score IN (-1, 0, 1)),  -- 1 dobré, 0 neurazí, -1 špatné
        rated_at TEXT    NOT NULL,            -- RRRR-MM-DD HH:MM
        PRIMARY KEY (dish_id, user_id)
    ) WITHOUT ROWID;
    CREATE INDEX dish_rating_user ON dish_rating (user_id);
    """,
    # 4 – historie cen akcí z Kupi.cz (storage/prices.py): jeden řádek = jedna akce (ID akce z Kupi.cz)
    """
    CREATE TABLE deal_price (
        deal_id    TEXT    PRIMARY KEY,       -- ID akce na Kupi.cz (data-discount)
        product    TEXT    NOT NULL,          -- produkt: slug z odkazu /sleva/<slug>, jinak název
        name       TEXT    NOT NULL,          -- název produktu, jak ho píše Kupi.cz
        amount     TEXT    NOT NULL,          -- balení („6x 0.5 l“, „1 kg“, '' když není)
        shop       TEXT    NOT NULL,          -- obchod („Lidl“, „Albert supermarket“…)
        category   TEXT    NOT NULL,          -- kategorie Kupi.cz
        price      REAL    NOT NULL,          -- Kč za balení
        unit_price REAL,                      -- Kč za 1 kg / 1 l, když ho Kupi.cz uvádí
        unit       TEXT,                      -- kg / l
        percent    INTEGER,                   -- sleva v %, když ji Kupi.cz uvádí
        valid_from TEXT,                      -- RRRR-MM-DD
        valid_to   TEXT,
        first_seen TEXT    NOT NULL,          -- RRRR-MM-DD, kdy jsme akci viděli poprvé
        last_seen  TEXT    NOT NULL
    );
    CREATE INDEX deal_price_product ON deal_price (product, amount);
    """,
    # 5 – hlídání akcí (storage/watches.py): co kdo hlídá a o kterých akcích už ví
    """
    CREATE TABLE watch (
        id         INTEGER PRIMARY KEY,
        user_id    INTEGER NOT NULL,          -- komu poslat zprávu (smaže si ho sám v /hlidat)
        query      TEXT    NOT NULL,          -- co hledat v názvu produktu („monster“, „pilsner“)
        max_price  REAL,                      -- cena do (Kč za kus), NULL = jakákoli akce
        created_at TEXT    NOT NULL
    );
    CREATE INDEX watch_user ON watch (user_id);
    CREATE TABLE watch_hit (
        watch_id    INTEGER NOT NULL REFERENCES watch (id) ON DELETE CASCADE,
        deal_id     TEXT    NOT NULL,         -- klíč akce (obchod|produkt|balení|cena|do), o které už člověk ví
        notified_at TEXT    NOT NULL,
        PRIMARY KEY (watch_id, deal_id)
    ) WITHOUT ROWID;
    """,
    # 6 – ceny točeného piva v hospodách (storage/beer.py): každá změna je nový řádek, aktuální = poslední
    """
    CREATE TABLE beer_price (
        id            INTEGER PRIMARY KEY,
        pub           TEXT    NOT NULL,       -- klíč podniku (pubs/venues.py PUBS)
        price         INTEGER,                -- Kč za 0,5 l, NULL = cena smazaná („nevíme“)
        beer          TEXT    NOT NULL DEFAULT '',  -- „Plzeň 12°“
        many          INTEGER NOT NULL DEFAULT 0,   -- víc druhů, cena je orientační („kolem“)
        user_id       INTEGER NOT NULL,       -- kdo cenu zadal (kvůli dohledání nesmyslů)
        created_at    TEXT    NOT NULL,       -- RRRR-MM-DD HH:MM
        reverted_from INTEGER                 -- vráceno na záznam s tímhle id
    );
    CREATE INDEX beer_price_pub ON beer_price (pub, id);
    """,
    # 7 – nastavení lidí (storage/prefs.py), zatím jen výchozí koleje z /koleje. Bez řádku = výchozí chování.
    """
    CREATE TABLE user_setting (
        user_id INTEGER NOT NULL,
        key     TEXT    NOT NULL,             -- „koleje“
        value   TEXT    NOT NULL,             -- „ppv“ / „purkyne“
        PRIMARY KEY (user_id, key)
    ) WITHOUT ROWID;
    """,
    # 8 – nastavení serverů (storage/settings.py, /nastaveni jen pro adminy). Bez řádku = výchozí hodnota.
    """
    CREATE TABLE guild_setting (
        guild_id   INTEGER NOT NULL,
        key        TEXT    NOT NULL,          -- „udalost_lidi“
        value      TEXT    NOT NULL,
        updated_by INTEGER NOT NULL,          -- kdo to naposledy změnil
        updated_at TEXT    NOT NULL,          -- RRRR-MM-DD HH:MM
        PRIMARY KEY (guild_id, key)
    ) WITHOUT ROWID;
    """,
]

LATEST = len(MIGRATIONS)
