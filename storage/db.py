"""SQLite databáze bota: jeden soubor (`data/bot.db`), jedno spojení, migrace a denní zálohy. Bez discord.py.

- Lokálně i v Dockeru je to soubor ve složce `data/` (v Dockeru volume `bot_data`), žádný další kontejner.
  Vývojový a produkční bot tak mají každý svou databázi a nemůžou si data přepsat.
- Testy používají databázi v paměti (`Database(":memory:")`), nic nezapisují na disk.
- Všechny dotazy jdou přes jedno spojení ve vlastním vlákně (aiosqlite), takže nezaseknou bota.
  Zámek zajistí, že se dotazy nepomíchají s rozpracovanou transakcí.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Iterable
from datetime import date
from pathlib import Path
from typing import Any

import aiosqlite

from .migrations import LATEST, MIGRATIONS

log = logging.getLogger(__name__)

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "bot.db"
BACKUP_KEEP = 7  # kolik denních záloh nechat

# WAL: čtení neblokuje zápis a soubor přežije i natvrdo ukončený proces. NORMAL je s WAL bezpečné
# (při výpadku proudu se můžou ztratit jen poslední zápisy, databáze se nerozbije).
_PRAGMAS = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
"""


class DatabaseUnavailable(RuntimeError):
    """Databáze není otevřená (nepodařilo se ji otevřít, nebo bot ještě nenastartoval)."""


class Database:
    def __init__(self, path: str | Path = DEFAULT_PATH) -> None:
        self.path = str(path)
        self._conn: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self.version = 0  # verze schématu po otevření

    @property
    def in_memory(self) -> bool:
        return self.path == ":memory:"

    @property
    def is_open(self) -> bool:
        return self._conn is not None

    async def open(self) -> None:
        if self._conn is not None:
            return
        if not self.in_memory:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # isolation_level=None: každý příkaz se hned uloží, víc příkazů najednou přes transaction()
        conn = await aiosqlite.connect(self.path, isolation_level=None)
        try:
            conn.row_factory = aiosqlite.Row
            await conn.executescript(_PRAGMAS)
            self.version = await migrate(conn)
        except BaseException:
            await conn.close()
            raise
        self._conn = conn
        log.info("🗄️ Databáze %s (schéma v%d)", self.path, self.version)

    async def close(self) -> None:
        if self._conn is None:
            return
        async with self._lock:
            with contextlib.suppress(Exception):
                await self._conn.execute("PRAGMA optimize")
            await self._conn.close()
            self._conn = None

    def _require(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise DatabaseUnavailable("Databáze není otevřená")
        return self._conn

    async def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        """Jeden příkaz (INSERT/UPDATE/DELETE…), hned uložený. Vrací počet změněných řádků."""
        conn = self._require()
        async with self._lock:
            cursor = await conn.execute(sql, tuple(params))
            return cursor.rowcount

    async def fetchall(self, sql: str, params: Iterable[Any] = ()) -> list[aiosqlite.Row]:
        conn = self._require()
        async with self._lock:
            return list(await conn.execute_fetchall(sql, tuple(params)))

    async def fetchone(self, sql: str, params: Iterable[Any] = ()) -> aiosqlite.Row | None:
        rows = await self.fetchall(sql, params)
        return rows[0] if rows else None

    @contextlib.asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Víc příkazů naráz: buď se uloží všechny, nebo (při chybě) žádný.

            async with db.transaction() as tx:
                await tx.execute("INSERT …", (…))
                await tx.execute("UPDATE …", (…))
        """
        conn = self._require()
        async with self._lock:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
            except BaseException:
                await conn.execute("ROLLBACK")
                raise
            await conn.execute("COMMIT")

    async def backup(self, folder: Path, day: date, keep: int = BACKUP_KEEP) -> Path | None:
        """Záloha do `folder/bot-RRRR-MM-DD.db` (jednou denně), starší než `keep` posledních se smažou.
        Vrací cestu k nové záloze, nebo None, když už dnešní existuje."""
        conn = self._require()
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"bot-{day.isoformat()}.db"
        if target.exists():
            return None
        async with self._lock:
            await conn.execute("VACUUM INTO ?", (str(target),))  # konzistentní a zmenšená kopie
        for old in sorted(folder.glob("bot-*.db"))[:-keep]:
            old.unlink()
        return target


async def migrate(conn: aiosqlite.Connection) -> int:
    """Doběhne chybějící migrace a vrátí verzi schématu."""
    row = await (await conn.execute("PRAGMA user_version")).fetchone()
    version = row[0]
    if version > LATEST:
        # databáze z novější verze bota (návrat přes BOT_TAG) – migrace jsou jen přidávací, takže to jde
        log.warning("Databáze má novější schéma (v%d) než tahle verze bota (v%d)", version, LATEST)
        return version
    for number, sql in enumerate(MIGRATIONS[version:], start=version + 1):
        log.info("🗄️ Migrace databáze na v%d", number)
        try:
            await conn.executescript(f"BEGIN IMMEDIATE;\n{sql}\nPRAGMA user_version = {number};\nCOMMIT;")
        except BaseException:
            if conn.in_transaction:
                await conn.execute("ROLLBACK")
            raise
        version = number
    return version
