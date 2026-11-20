"""Slevy a letáky z Kupi.cz: parsery nad uloženými stránkami (20. 11. 2026) a výběr akcí pro obchody."""

from datetime import date
from pathlib import Path

import pytest

from cogs import slevy
from shops import kupi
from shops.service import STORES

FIX = Path(__file__).parent / "fixtures"
DAY = date(2026, 11, 20)  # pátek


def read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("platí do úterý 24. 11.", (None, date(2026, 11, 24))),
        ("čt 26. 11. – ne 29. 11.", (date(2026, 11, 26), date(2026, 11, 29))),
        ("platí po 23. 11. – st 25. 11.", (date(2026, 11, 23), date(2026, 11, 25))),
        ("zítra končí", (None, date(2026, 11, 21))),
        ("dnes končí", (None, DAY)),
        ("", (None, None)),
    ],
)
def test_parse_validity(text, expected):
    assert kupi.parse_validity(text, DAY) == expected


def test_parse_validity_over_new_year():
    assert kupi.parse_validity("platí do neděle 3. 1.", date(2026, 12, 30)) == (None, date(2027, 1, 3))


def test_parse_deals():
    deals, has_next = kupi.parse_deals(read("kupi_drubez_1.html"), "drubez", DAY, page=1)
    assert has_next and len(deals) >= 20
    lidl = next(d for d in deals if d.shop == "Lidl" and d.product == "Kuřecí prsa s kostí")
    assert (lidl.amount, lidl.price, lidl.valid_to) == ("1 kg", "99,90 Kč", date(2026, 11, 22))
    assert lidl.url == "https://www.kupi.cz/sleva/kureci-prsa-s-kosti"
    billa = next(d for d in deals if d.product == "Kuře Vocílka")
    assert billa.percent == 44
    assert {"Albert hypermarket", "Albert supermarket"} <= {d.shop for d in deals}


def test_parse_deals_last_page():
    _, has_next = kupi.parse_deals(read("kupi_drubez_3.html"), "drubez", DAY, page=3)
    assert not has_next


def test_parse_store():
    lidl = kupi.parse_store(read("kupi_lidl_kralovo_pole.html"), DAY)
    assert lidl.hours[DAY.weekday()] == "7:00–21:00"
    assert len(lidl.leaflets) == 4 and all(l.url.startswith("https://www.kupi.cz/letak/") for l in lidl.leaflets)
    billa = kupi.parse_store(read("kupi_billa_srbska.html"), DAY)
    assert [l.title for l in billa.leaflets] == ["BILLA malý leták"]
    assert billa.leaflets[0].valid_to == date(2026, 11, 24) and billa.leaflets[0].image


def _deal(shop, pct=None, valid_from=None, valid_to=date(2026, 11, 24), category="drubez", name="Kuře"):
    return kupi.Deal(f"{shop}{pct}{valid_from}{name}", name, "1 kg", shop, "99,90 Kč", pct, valid_from, valid_to, category, kupi.BASE)


def test_store_deals_filter_and_order():
    deals = [
        _deal("Albert hypermarket", 50),  # jiný formát Albertu -> pryč
        _deal("Albert", 20, name="A"),
        _deal("Albert supermarket", 40, name="B"),
        _deal("Albert", None, name="C"),
        _deal("Albert", 60, valid_from=date(2026, 11, 26), valid_to=date(2026, 11, 29), name="D"),  # budoucí
        _deal("Albert", 70, valid_to=date(2026, 11, 19), name="E"),  # už skončila
        _deal("Albert", 30, category="hovezi-maso", name="F"),
        _deal("Lidl", 99, name="G"),
    ]
    albert = STORES["albert"]
    assert [d.product for d in slevy.store_deals(deals, albert, slevy.ALL, DAY)] == ["B", "F", "A", "C", "D"]
    assert [d.product for d in slevy.store_deals(deals, albert, "drubez", DAY)] == ["B", "A", "C", "D"]


def test_validity_labels():
    assert slevy._validity(None, date(2026, 11, 22), DAY) == "do ne 22. 11."
    assert slevy._validity(date(2026, 11, 26), date(2026, 11, 29), DAY) == "🔜 od čt 26. 11."
    assert slevy._validity(None, DAY, DAY) == "⏳ končí dnes"
    assert slevy._validity(None, date(2026, 11, 21), DAY) == "⏳ končí zítra"


def test_leaflets_embed_merges_branches():
    page = kupi.parse_store(read("kupi_lidl_kralovo_pole.html"), DAY)
    lidl = STORES["lidl"]
    pages = {b.kupi_path: page for b in lidl.branches}  # 3 pobočky, stejné letáky -> bez duplicit
    embed = slevy._leaflets_embed(lidl, pages, DAY)
    lines = embed.description.split("\n")
    assert lines[0] == "📍 Palackého, Šumavská, Bayerova"
    assert lines[1] == "🕐 Dnes 7:00–21:00"
    assert sum(l.startswith("📰") for l in lines) == 4
    assert lines[2].endswith("· do ne 22. 11.")  # nejdřív platný, pak budoucí
    assert embed.thumbnail.url


def test_buttons_unique_for_every_state():
    for view, flt in [(slevy.VIEW_LEAFLETS, slevy.ALL)] + [(slevy.VIEW_MEAT, f) for f in slevy.MEAT_FILTERS]:
        ui = slevy.build_view(view, flt)
        ids = [getattr(getattr(i, "item", i), "custom_id", None) for i in ui.children]
        ids = [i for i in ids if i]
        assert len(ids) == len(set(ids))
