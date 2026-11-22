"""Databáze (storage/): migrace, transakce, zálohy, statistiky commandů a /statistiky."""

import asyncio
import sqlite3
from datetime import date
from types import SimpleNamespace

import pytest

from cogs import statistiky
from storage import Database, DatabaseUnavailable, db as db_mod, migrations, usage
from storage.__main__ import main as cli

DAY = date(2026, 11, 23)


def run(coro):
    return asyncio.run(coro)


async def _memory() -> Database:
    db = Database(":memory:")
    await db.open()
    return db


def test_fresh_database_has_latest_schema():
    async def go():
        db = await _memory()
        tables = {r["name"] for r in await db.fetchall("SELECT name FROM sqlite_master WHERE type = 'table'")}
        await db.close()
        return db.version, tables

    version, tables = run(go())
    assert version == migrations.LATEST
    assert "command_usage" in tables


def test_file_database_migrates_once_and_keeps_data(tmp_path):
    path = tmp_path / "data" / "bot.db"  # složka se vytvoří sama

    async def go():
        db = Database(path)
        await db.open()
        await usage.record(db, "ppv", DAY)
        await db.close()
        again = Database(path)
        await again.open()  # migrace už neběží znovu, data zůstala
        rows = await usage.top(again)
        mode = (await again.fetchone("PRAGMA journal_mode"))[0]
        await again.close()
        return rows, mode, again.version

    rows, mode, version = run(go())
    assert rows == [usage.Usage("ppv", 1)]
    assert mode == "wal" and version == migrations.LATEST


def test_failed_migration_rolls_back(tmp_path, monkeypatch):
    path = tmp_path / "bot.db"
    broken = [*migrations.MIGRATIONS, "CREATE TABLE half (x INTEGER); THIS IS NOT SQL;"]
    monkeypatch.setattr(db_mod, "MIGRATIONS", broken)
    monkeypatch.setattr(db_mod, "LATEST", len(broken))
    with pytest.raises(sqlite3.Error):
        run(Database(path).open())
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == len(broken) - 1  # předchozí migrace prošly
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'half'").fetchone()[0] == 0  # nic napůl


def test_newer_schema_from_newer_bot_still_opens(tmp_path):
    path = tmp_path / "bot.db"
    conn = sqlite3.connect(path)
    conn.execute(f"PRAGMA user_version = {migrations.LATEST + 5}")
    conn.close()

    async def go():
        db = Database(path)
        await db.open()
        await db.close()
        return db.version

    assert run(go()) == migrations.LATEST + 5


def test_transaction_is_all_or_nothing():
    async def go():
        db = await _memory()
        with pytest.raises(RuntimeError):
            async with db.transaction() as tx:
                await tx.execute("INSERT INTO command_usage (day, command, count) VALUES ('2026-11-23', 'a', 1)")
                raise RuntimeError("něco se pokazilo")
        async with db.transaction() as tx:
            await tx.execute("INSERT INTO command_usage (day, command, count) VALUES ('2026-11-23', 'b', 1)")
        rows = [r["command"] for r in await db.fetchall("SELECT command FROM command_usage")]
        await db.close()
        return rows

    assert run(go()) == ["b"]


def test_closed_database_says_so():
    with pytest.raises(DatabaseUnavailable):
        run(Database(":memory:").fetchall("SELECT 1"))


def test_backup_once_a_day_and_keeps_last(tmp_path):
    async def go():
        db = Database(tmp_path / "bot.db")
        await db.open()
        await usage.record(db, "pivo", DAY)
        folder = tmp_path / "backups"
        made = [await db.backup(folder, date(2026, 11, d), keep=3) for d in (20, 21, 22, 23)]
        again = await db.backup(folder, date(2026, 11, 23), keep=3)
        await db.close()
        return folder, made, again

    folder, made, again = run(go())
    assert all(made) and again is None
    assert sorted(p.name for p in folder.iterdir()) == ["bot-2026-11-21.db", "bot-2026-11-22.db", "bot-2026-11-23.db"]
    copy = sqlite3.connect(folder / "bot-2026-11-23.db")
    assert copy.execute("SELECT command, count FROM command_usage").fetchall() == [("pivo", 1)]


def test_usage_counts_per_period():
    async def go():
        db = await _memory()
        for day, command in [(date(2026, 11, 1), "mhd"), (DAY, "ppv"), (DAY, "ppv"), (DAY, "mhd"), (DAY, "kola")]:
            await usage.record(db, command, day)
        result = (await usage.top(db), await usage.top(db, DAY), await usage.first_day(db))
        await db.close()
        return result

    everything, today, first = run(go())
    assert everything == [usage.Usage("mhd", 2), usage.Usage("ppv", 2), usage.Usage("kola", 1)]
    assert today[0] == usage.Usage("ppv", 2)
    assert first == date(2026, 11, 1)


def test_statistiky_message_and_listener(monkeypatch):
    monkeypatch.setattr(statistiky, "today", lambda: DAY)

    async def go():
        db = await _memory()
        cog = statistiky.Statistiky(SimpleNamespace(db=db))
        for name in ("ppv", "ppv", "pivo"):
            await cog.on_app_command_completion(None, SimpleNamespace(qualified_name=name))
        result = await statistiky.build_message(db, "7")
        await db.close()
        return result

    content, (embed,), view = run(go())
    assert "celkem **3×**" in content and "sbírá se od 23. 11. 2026" in content
    cards = [f for f in embed.fields if f.name != "​"]
    assert [(f.name, f.value.split("\n")[0]) for f in cards] == [("/ppv", "**2×**"), ("/pivo", "**1×**")]
    assert [c.custom_id for c in view.children] == ["statistiky:7", "statistiky:30", "statistiky:vse"]


def test_listener_without_database_does_nothing():
    cog = statistiky.Statistiky(SimpleNamespace(db=Database(":memory:")))  # neotevřená
    run(cog.on_app_command_completion(None, SimpleNamespace(qualified_name="ppv")))


def test_cli_overview_and_query(tmp_path, monkeypatch, capsys):
    path = tmp_path / "bot.db"

    async def go():
        db = Database(path)
        await db.open()
        await usage.record(db, "kola", DAY)
        await db.close()

    run(go())
    monkeypatch.setenv("DB_PATH", str(path))
    cli(["storage"])
    assert f"schéma v{migrations.LATEST}" in capsys.readouterr().out
    cli(["storage", "SELECT command, count FROM command_usage"])
    out = capsys.readouterr().out
    assert "kola" in out and "(1 řádek)" in out
    with pytest.raises(sqlite3.OperationalError):  # jen pro čtení
        cli(["storage", "DELETE FROM command_usage"])
