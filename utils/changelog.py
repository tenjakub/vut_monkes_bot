"""Načtení CHANGELOG.md (novinky pro uživatele) – pro /novinky a číslo verze ve statusu."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
URL = "https://github.com/tenjakub/vut_monkes_bot/blob/main/CHANGELOG.md"

_HEADING_RE = re.compile(
    r"^## (?P<version>\d+(?:\.\d+)*) · (?P<date>\d{4}-\d{2}-\d{2})(?: · (?P<title>.+?))?\s*$"
)
_SUBHEADING_RE = re.compile(r"^#{3,} +(.+?)\s*$")


@dataclass(frozen=True)
class Release:
    version: str
    date: date
    title: str | None
    body: str  # markdown pro Discord (podnadpisy převedené na tučné)


def parse(text: str) -> list[Release]:
    """Verze v pořadí ze souboru (nejnovější první). Text před první verzí se ignoruje."""
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    releases: list[Release] = []
    current: dict | None = None

    def flush() -> None:
        if current is not None:
            body = "\n".join(current["lines"]).strip()
            releases.append(Release(current["version"], current["date"], current["title"], body))

    for line in text.splitlines():
        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            current = {
                "version": heading["version"],
                "date": date.fromisoformat(heading["date"]),
                "title": heading["title"],
                "lines": [],
            }
        elif current is not None:
            sub = _SUBHEADING_RE.match(line)
            current["lines"].append(f"**{sub.group(1)}**" if sub else line.rstrip())
    flush()
    return releases


@lru_cache(maxsize=1)
def load() -> tuple[Release, ...]:
    try:
        return tuple(parse(PATH.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return ()


def current_version() -> str | None:
    releases = load()
    return releases[0].version if releases else None
