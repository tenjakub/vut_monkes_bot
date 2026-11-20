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
    states = [(slevy.VIEW_LEAFLETS, slevy.ALL, False)] + [
        (v, f, only) for v, dv in slevy.DEAL_VIEWS.items() for f in (slevy.ALL, *dv.filters) for only in (False, True)
    ]
    for view, flt, only in states:
        ui = slevy.build_view(view, flt, only)
        ids = [getattr(getattr(i, "item", i), "custom_id", None) for i in ui.children]
        ids = [i for i in ids if i]
        assert len(ids) == len(set(ids)), (view, flt, only)
        assert len(ui.children) <= 10


def test_old_button_ids_still_match():
    """Tlačítka na zprávách z verze 1.2 (bez příznaku "jen se slevou") musí fungovat dál."""
    import re as _re

    pattern = slevy.SlevyButton.__discord_ui_compiled_template__
    old = _re.fullmatch(pattern, "slevy:maso:drubez:f")
    assert old and old["only"] is None and old["filter"] == "drubez"
    new = _re.fullmatch(pattern, "slevy:napoje:limonady:1:o")
    assert new and new["only"] == "1"


def test_only_discount_filter():
    deals = [_deal("BILLA", 30, name="A"), _deal("BILLA", None, name="B")]
    assert [d.product for d in slevy.store_deals(deals, STORES["billa"], slevy.ALL, DAY, only_discount=True)] == ["A"]


def test_drinks_only_sugar_free_sure_first():
    def drink(name, note="", pct=None, cat="limonady"):
        return kupi.Deal(name + note, name, "", "Lidl", "19,90 Kč", pct, None, date(2026, 11, 24), cat, kupi.BASE, note)

    deals = [
        drink("Limonáda Pepsi", "regular", 50),  # výslovně s cukrem -> pryč
        drink("Energetický nápoj Red Bull", "různé druhy, plech", 40, "energeticke-a-iontove-napoje"),  # možná
        drink("Limonáda Coca Cola Zero", "plech"),  # jistě
        drink("Kofola Nulka bez cukru"),  # jistě
        drink("Limonáda Top Topic", "různé druhy"),  # značka bez verze zero -> pryč
    ]
    got = slevy.store_deals(deals, STORES["lidl"], slevy.ALL, DAY, view=slevy.VIEW_DRINKS)
    assert [d.product for d in got] == ["Kofola Nulka bez cukru", "Limonáda Coca Cola Zero", "Energetický nápoj Red Bull"]
    embed = slevy._deals_embed(STORES["lidl"], slevy.DEAL_VIEWS["napoje"], deals, slevy.ALL, False, DAY, 1500, False)
    text = embed.description
    assert text.index("✅ Bez cukru") < text.index("Coca Cola Zero") < text.index("🤷") < text.index("Red Bull")
    assert "Limonáda" not in text and "Energetický nápoj" not in text  # zkrácené názvy
