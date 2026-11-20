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


# --- pivo ---------------------------------------------------------------------------------------

from shops.service import BEER_BOTTLE, BEER_CAN, BEER_PACK, beer_pack, price_per_liter  # noqa: E402


def _beer(name, amount="0.5 l", note="", price="15,90 Kč", unit="31,80 Kč / 1 l", pct=None, shop="BILLA"):
    return kupi.Deal(f"{name}{amount}{note}{price}", name, amount, shop, price, pct, None, date(2026, 11, 24),
                     "pivo", kupi.BASE, note, unit)


@pytest.mark.parametrize(
    ("deal", "expected"),
    [
        (_beer("Pivo světlý ležák 12° Velkopopovický Kozel", note="+3 Kč záloha na láhev"), BEER_BOTTLE),
        (_beer("Pivo světlý ležák 12° Staropramen", note="plech"), BEER_CAN),
        (_beer("Pivo Originál 10° Gambrinus", "6x 0.5 l", "plech", "95,90 Kč", "31,97 Kč / 1 l"), BEER_PACK),
        (_beer("Pivo Krušovice", "10x 0.5 l", "+30 Kč záloha na láhve", "127,90 Kč", "25,58 Kč / 1 l"), BEER_PACK),
        (_beer("Pivo Litovel", "", "basa, 20 lahví"), BEER_PACK),
        (_beer("Pivo světlý ležák Corona Extra", "0.33 l", "sklo"), BEER_BOTTLE),
        (_beer("Pivo světlé Březňák", "2 l", "pet láhev"), None),  # PET
        (_beer("Pivo Svijanský Máz", "5 l", "", "279,90 Kč", "55,98 Kč / 1 l"), None),  # soudek
        (_beer("Pivo Pilsner Urquell - dárkové balení", "8x 0.5 l", "+ krýgl, +24 Kč záloha na láhve"), None),
        (_beer("Pivo Pilsner Urquell", "6x 0.5 l", "metr piv, plech"), None),
        (_beer("Pivo Retro láhev Pilsner Urquell", "1 l", "", "229,90 Kč", "229,90 Kč / 1 l"), None),  # sběratelská
    ],
)
def test_beer_pack(deal, expected):
    assert beer_pack(deal) == expected


def test_price_per_liter():
    assert price_per_liter(_beer("x", unit="1 031,97 Kč / 1 l")) == 1031.97
    assert price_per_liter(_beer("x", unit="99,90 Kč / 1 kg")) is None


def test_beer_view_lines_and_filters():
    deals = [
        _beer("Pivo světlý ležák 12° Staropramen", note="plech", pct=33),
        _beer("Pivo Originál 10° Gambrinus", "6x 0.5 l", "plech", "95,90 Kč", "31,97 Kč / 1 l"),
        _beer("Pivo světlé Braník", note="+3 Kč záloha na láhev", price="10,90 Kč", unit="21,80 Kč / 1 l"),
        _beer("Pivo světlé Březňák", "2 l", "pet láhev"),
    ]
    billa = STORES["billa"]
    assert len(slevy.store_deals(deals, billa, slevy.ALL, DAY, view=slevy.VIEW_BEER)) == 3
    packs = slevy.store_deals(deals, billa, BEER_PACK, DAY, view=slevy.VIEW_BEER)
    assert [d.product for d in packs] == ["Pivo Originál 10° Gambrinus"]
    line = slevy._deal_line(packs[0], slevy.DEAL_VIEWS[slevy.VIEW_BEER], DAY)
    assert line.startswith("📦 Originál 10° Gambrinus 6× 0,5 l — **95,90 Kč** (32 Kč/l)")
    # bez slevy v % řadí podle ceny za litr (Braník 21,80 Kč/l před Gambrinusem 31,97 Kč/l)
    no_pct = [d.product for d in slevy.store_deals(deals, billa, slevy.ALL, DAY, view=slevy.VIEW_BEER)[1:]]
    assert no_pct == ["Pivo světlé Braník", "Pivo Originál 10° Gambrinus"]


def test_parse_real_beer_page():
    deals, has_next = kupi.parse_deals(read("kupi_pivo_1.html"), "pivo", DAY, page=1)
    assert has_next
    multipack = next(d for d in deals if d.amount.startswith("6x"))
    assert multipack.unit_price.endswith("/ 1 l")


def _ids(ui):
    return [getattr(getattr(i, "item", i), "custom_id", None) for i in ui.children]


def test_deal_views_default_to_only_discount():
    assert slevy.DEFAULT_ONLY_DISCOUNT
    # z letáků vedou tlačítka do výpisů akcí rovnou se zapnutým "jen se slevou"
    ids = _ids(slevy.build_view(slevy.VIEW_LEAFLETS))
    assert "slevy:maso:vse:1:g" in ids and "slevy:pivo:vse:1:g" in ids
    # když ho uživatel vypne, přenáší se vypnutý i do ostatních výpisů
    ids = _ids(slevy.build_view(slevy.VIEW_MEAT, slevy.ALL, only_discount=False))
    assert "slevy:pivo:vse:0:g" in ids


def test_generic_store_names_branch_in_leaflets():
    assert [s.name for s in STORES.values()] == ["Lidl", "BILLA", "Albert", "Globus"]
    page = kupi.parse_store(read("kupi_billa_srbska.html"), DAY)
    embed = slevy._leaflets_embed(STORES["billa"], {STORES["billa"].branches[0].kupi_path: page}, DAY)
    assert embed.title == "🛒 BILLA"
    assert embed.description.startswith("📍 Srbská\n🕐 Dnes 7:00–22:00")
