"""Nahlédnutí do databáze jen pro čtení – lokálně i v konzoli kontejneru (Portainer → Console):

    python -m storage                          # soubor, verze schématu, tabulky a počty řádků
    python -m storage "SELECT * FROM command_usage ORDER BY day DESC LIMIT 20"

Databáze se otevírá jen pro čtení, takže tím nic nerozbiješ ani za běhu bota. Cesta je z DB_PATH,
jinak data/bot.db.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

from .db import DEFAULT_PATH


def _connect(path: Path) -> sqlite3.Connection:
    if not path.exists():
        raise SystemExit(f"Databáze {path} neexistuje (vytvoří ji bot při startu).")
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)


def _rows(n: int) -> str:
    return f"{n} řádek" if n == 1 else (f"{n} řádky" if 2 <= n <= 4 else f"{n} řádků")


def _print_table(cursor: sqlite3.Cursor, rows: list[tuple]) -> None:
    headers = [d[0] for d in cursor.description or []]
    cells = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [max(len(h), *(len(r[i]) for r in cells)) if cells else len(h) for i, h in enumerate(headers)]
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    print("  ".join("-" * w for w in widths))
    for r in cells:
        print("  ".join(v.ljust(w) for v, w in zip(r, widths)))
    print(f"({_rows(len(rows))})")


def main(argv: list[str]) -> None:
    path = Path(os.environ.get("DB_PATH") or DEFAULT_PATH)
    conn = _connect(path)
    if len(argv) > 1:
        cursor = conn.execute(" ".join(argv[1:]))
        _print_table(cursor, cursor.fetchall())
        return
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    print(f"{path} · schéma v{version} · {path.stat().st_size / 1024:.0f} kB")
    for (name,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
        count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
        print(f"  {name}: {_rows(count)}")


if __name__ == "__main__":
    main(sys.argv)
