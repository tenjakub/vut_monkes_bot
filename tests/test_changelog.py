"""CHANGELOG.md se píše ručně – testy hlídají, že ho bot umí přečíst a /novinky ho správně stránkuje."""

import re
from datetime import date

import pytest

from cogs import novinky
from utils import changelog


def _version_key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def test_real_changelog_is_valid():
    releases = changelog.parse(changelog.PATH.read_text(encoding="utf-8"))
    assert releases, "CHANGELOG.md musí mít aspoň jednu verzi ve formátu '## 1.2 · RRRR-MM-DD · název'"
    versions = [_version_key(r.version) for r in releases]
    assert versions == sorted(versions, reverse=True) and len(set(versions)) == len(versions), (
        "verze musí jít od nejnovější a nesmí se opakovat"
    )
    dates = [r.date for r in releases]
    assert dates == sorted(dates, reverse=True), "data musí jít od nejnovějšího"
    for r in releases:
        assert r.body.strip(), f"verze {r.version} nemá žádný popis"
        assert len(r.body) <= 4000, f"popis verze {r.version} je na Discord moc dlouhý"
    # každý nadpis verze ve formátu "## <číslo>" se musí naparsovat (překlep v datu apod.)
    text = re.sub(r"<!--.*?-->", "", changelog.PATH.read_text(encoding="utf-8"), flags=re.S)
    raw = [l for l in text.splitlines() if l.startswith("## ")]
    assert len(raw) == len(releases), "nějaký nadpis '## …' nemá správný formát"


def test_parse_subheadings_and_comments():
    text = """# Novinky
<!-- ## 9.9 · 2030-01-01 · v komentáři se ignoruje -->
## 1.2 · 2026-12-01 · Něco
- a
### Sekce
- b
## 1.1 · 2026-11-20
- c
"""
    r = changelog.parse(text)
    assert [x.version for x in r] == ["1.2", "1.1"]
    assert r[0].title == "Něco" and r[1].title is None
    assert r[0].body == "- a\n**Sekce**\n- b"
    assert r[1].date == date(2026, 11, 20)


@pytest.fixture
def seven_releases(monkeypatch):
    releases = tuple(
        changelog.Release(f"1.{i}", date(2026, 11, 1 + i), None, f"- změna {i}") for i in range(6, -1, -1)
    )
    monkeypatch.setattr(changelog, "load", lambda: releases)
    return releases


def _custom_ids(view):
    return [getattr(getattr(i, "item", i), "custom_id", None) for i in view.children]


def test_novinky_pages(seven_releases):
    content, embeds, view = novinky.build_message(0)
    assert [e.title for e in embeds] == ["🆕 Verze 1.6", "Verze 1.5", "Verze 1.4"]
    assert "strana 1/3" in content
    ids = [i for i in _custom_ids(view) if i]
    assert len(ids) == len(set(ids))  # Discord vyžaduje unikátní custom_id

    content, embeds, view = novinky.build_message(2)
    assert [e.title for e in embeds] == ["Verze 1.0"]
    assert "strana 3/3" in content

    # stránka mimo rozsah (stará zpráva, mezitím ubyly verze) se nerozbije
    _, embeds, _ = novinky.build_message(99)
    assert [e.title for e in embeds] == ["Verze 1.0"]
    assert len({e.url for e in novinky.build_message(0)[1]}) == 3  # unikátní URL, jinak je Discord sloučí


def test_novinky_single_page_has_only_link(monkeypatch):
    monkeypatch.setattr(changelog, "load", lambda: (changelog.Release("1.0", date(2026, 11, 20), "X", "- a"),))
    content, embeds, view = novinky.build_message(0)
    assert len(view.children) == 1 and "strana" not in content
