"""🍺 /cena-piva: seznam piv v hospodě, úpravy jednotlivých piv, vrácení na starší stav a ceny v /na-pivo."""

import asyncio
from types import SimpleNamespace

import pytest

from cogs import cenapiva, napivo
from pubs import beers, venues
from pubs.beers import BeerError, PubBeers, Tap
from storage import beer
from tests.fakes import Interaction, memory_db, with_values
from utils.text import clean


def run(coro):
    return asyncio.run(coro)


# --- pubs.beers: stav hospody (bez databáze) --------------------------------------------------------


@pytest.mark.parametrize(("text", "expected"), [("59", 59), (" 59 Kč", 59), ("59,-", 59)])
def test_parse_price(text, expected):
    assert beers.parse_price(text) == expected


def test_parse_price_optional():
    assert beers.parse_price("  ", required=False) is None
    with pytest.raises(BeerError):
        beers.parse_price("")


@pytest.mark.parametrize("text", ["5", "9999", "levné", "59,50", "-59"])
def test_parse_price_nonsense(text):
    with pytest.raises(BeerError):
        beers.parse_price(text)


def _taps(*prices):
    state = PubBeers()
    for i, price in enumerate(prices):
        state, _ = beers.add(state, f"Pivo {i}", price)
    return state


def test_one_or_two_beers_are_listed():
    state, change = beers.add(PubBeers(), "Plzeň 12°", 59)
    assert change == "➕ Plzeň 12° · 59 Kč"
    assert (state.price_text, state.text) == ("59 Kč", "💰 Plzeň 12° · 59 Kč")
    state, _ = beers.add(state, "Kozel 11°", 45)
    assert state.summary == "Kozel 11° · 45 Kč, Plzeň 12° · 59 Kč"  # seřazené podle ceny
    assert state.price_text == "45–59 Kč"


def test_more_beers_show_median():
    assert _taps(45, 59, 70).summary == "3 piva · ~59 Kč"
    assert _taps(40, 50, 60, 90).price_text == "~55 Kč"
    assert _taps(*range(40, 45)).summary == "5 piv · ~42 Kč"


def test_many_kinds_override_list():
    state, change = beers.set_many(_taps(45, 59), 70)
    assert change == "🍻 víc druhů · ~70 Kč"
    assert (state.price_text, state.summary) == ("~70 Kč", "víc druhů · ~70 Kč")
    state, change = beers.set_many(state, None)
    assert change == "🍻 zrušeno „víc druhů“" and state.price_text == "45–59 Kč"


def test_edit_rename_and_remove():
    state, _ = beers.add(PubBeers(), "Plzeň 12°", 59)
    state, change = beers.add(state, "plzeň 12°", 62, original="Plzeň 12°")
    assert change == "✏️ Plzeň 12° → plzeň 12° · 62 Kč"
    state, change = beers.add(state, "plzeň 12°", 64, original="plzeň 12°")
    assert change == "✏️ plzeň 12° · 62 → 64 Kč"
    state, change = beers.remove(state, "PLZEŇ 12°")
    assert change == "🗑️ plzeň 12°" and state.empty and state.text == ""


@pytest.mark.parametrize(("edit", "message"), [
    (lambda s: beers.add(s, "plzeň 12°", 50), "už v seznamu je"),
    (lambda s: beers.add(s, "Kozel", 50, original="Kozel"), "už v seznamu není"),
    (lambda s: beers.add(s, "Plzeň 12°", 59, original="Plzeň 12°"), "Nic se nezměnilo"),
    (lambda s: beers.remove(s, "Kozel"), "už v seznamu není"),
    (lambda s: beers.set_many(s, None), "Nic se nezměnilo"),
])
def test_invalid_changes(edit, message):
    state, _ = beers.add(PubBeers(), "Plzeň 12°", 59)
    with pytest.raises(BeerError, match=message):
        edit(state)


def test_max_taps():
    state = _taps(*[50] * beers.MAX_TAPS)
    with pytest.raises(BeerError, match="nevejde"):
        beers.add(state, "Další", 50)


# --- text od lidí ---------------------------------------------------------------------------------


@pytest.mark.parametrize(("text", "expected"), [
    ("**Plzeň** 12°", "Plzeň 12°"),
    ("@everyone Kozel", "everyone Kozel"),
    ("<@123> [klik](https://x.cz)", "123 klik (https //x.cz)"),
    ("Pilsner\nUrquell ~~", "Pilsner Urquell"),
    ("`kód` <:emoji:1>", "kód emoji 1"),
    ("Černá Hora 11°", "Černá Hora 11°"),
    ("*** ___", ""),
])
def test_clean(text, expected):
    assert clean(text) == expected


def test_clean_limit():
    assert clean("a" * 100, limit=10) == "a" * 10


# --- /cena-piva v Discordu ------------------------------------------------------------------------


async def _tap(client, user_id, name, price, original=None):
    """Odešle okno piva (přidat, nebo upravit `original`)."""
    state = await cenapiva._current(Interaction(client), "burza")
    modal = cenapiva.TapModal("burza", state.find(original) if original else None)
    modal.name._value, modal.price._value = name, price
    interaction = Interaction(client, user_id=user_id)
    await modal.on_submit(interaction)
    return interaction.last()


def _shown(msg: dict) -> str:
    """Celý text zprávy: hláška nad profilem + embed (nadpis, popis, kartičky)."""
    e = msg.get("embed")
    parts = [msg.get("content") or ""]
    if e:
        parts += [e.title or "", e.description or ""] + [f"{f.name}: {f.value}" for f in e.fields]
    return "\n".join(parts)


async def _many(client, user_id, price):
    modal = cenapiva.ManyModal("burza", None)
    modal.price._value = price
    interaction = Interaction(client, user_id=user_id)
    await modal.on_submit(interaction)
    return interaction.last()


def test_add_edit_remove_and_revert(monkeypatch):
    monkeypatch.setattr(venues, "beer_prices", {})

    async def go():
        async with memory_db() as db:
            client = SimpleNamespace(db=db)
            cog = cenapiva.CenaPiva(client)
            opened = Interaction(client)
            await cog.cena_piva.callback(cog, opened)
            picked = Interaction(client)
            await with_values(cenapiva.PubSelect("e"), "burza").callback(picked)
            add = Interaction(client)
            await cenapiva.AddButton("burza").callback(add)
            out = {"opened": opened.last(), "picked": picked.last(), "add": add.response.calls[0]}
            out["first"] = await _tap(client, 1, "**Plzeň** 12°", "59 Kč")
            out["second"] = await _tap(client, 1, "Kozel 11°", "45")
            out["napivo"] = napivo.place_lines("burza")
            edit = Interaction(client)
            await with_values(cenapiva.TapSelect("burza"), "Plzeň 12°").callback(edit)
            out["edit"] = edit.response.calls[0]
            out["vandal"] = await _tap(client, 2, "zadarmo", "499", original="Plzeň 12°")
            out["bad"] = await _tap(client, 2, "Kozel", "hodně")
            out["removed"] = await _tap(client, 2, "Kozel 11°", "", original="Kozel 11°")
            first_two = (await beer.history(db, "burza"))[-2]
            back = Interaction(client, user_id=1)
            await with_values(cenapiva.RevertSelect("burza"), str(first_two.id)).callback(back)
            out["back"] = back.last()
            again = Interaction(client, user_id=1)
            await with_values(cenapiva.RevertSelect("burza"), str(first_two.id)).callback(again)
            out["again"] = again.last()
            public = Interaction(client)
            await cog.co_toci.callback(cog, public, SimpleNamespace(value="burza"))
            out["public"] = public.last()
            out["history"] = await beer.history(db, "burza")
            out["cache"] = dict(venues.beer_prices)
            return out

    out = run(go())
    assert "**Pivní burza** — _nevíme_" in out["opened"]["content"] and out["opened"]["ephemeral"]
    assert out["picked"]["content"] is None and "_Zatím nikdo nezadal, co tu točí._" in _shown(out["picked"])
    assert out["add"][0] == "modal"
    assert out["first"]["content"] == "✅ Uloženo: ➕ Plzeň 12° · 59 Kč"  # bez markdownu
    second = _shown(out["second"])
    assert "🍺 Kozel 11°: **45 Kč**\n-# od " in second and "🍺 Plzeň 12°: **59 Kč**" in second
    assert "🍺 Točí **2 piva** · 45–59 Kč" in second
    assert out["napivo"][1].startswith("-# 💰 Kozel 11° · 45 Kč, Plzeň 12° · 59 Kč (")
    assert out["edit"][0] == "modal"
    assert "✏️ Plzeň 12° → zadarmo · 499 Kč" in _shown(out["vandal"])
    assert "nechápu" in out["bad"]["content"] and out["bad"]["ephemeral"]
    assert out["removed"]["content"] == "✅ Uloženo: 🗑️ Kozel 11°"
    assert out["back"]["content"].startswith("✅ Uloženo: ↩️ vráceno na stav z ")
    assert "<@1>" in _shown(out["back"]) and "<@2>" in _shown(out["back"])  # kdo co změnil, je vidět
    public = out["public"]
    assert not public.get("ephemeral") and "🍺 Pivní burza" in _shown(public)  # /co-toci vidí všichni
    assert "🍺 Plzeň 12°: **59 Kč**" in _shown(public) and "🍺 Kozel 11°" in _shown(public)
    assert out["again"]["content"] == "Tohle už teď platí."
    history = out["history"]
    assert [len(v.state.taps) for v in history] == [2, 1, 2, 2, 1]
    assert history[0].reverted_from == history[-2].id
    assert out["cache"]["burza"].summary == "Kozel 11° · 45 Kč, Plzeň 12° · 59 Kč"


def test_profile_offers_editing_only_what_exists(monkeypatch):
    monkeypatch.setattr(venues, "beer_prices", {})

    async def go():
        async with memory_db() as db:
            client = SimpleNamespace(db=db)
            empty = await cenapiva.profile(db, "burza")
            await _tap(client, 1, "Plzeň 12°", "59")
            one = await cenapiva.profile(db, "burza")
            await _tap(client, 1, "Kozel 11°", "45")
            two = await cenapiva.profile(db, "burza")
            return empty, one, two

    def ids(view):
        return [c.item.custom_id for c in view.children]

    empty, one, two = (shown["view"] for shown in run(go()))
    assert ids(empty) == ["pivocena:a:burza", "pivocena:m:burza", "pivocena:p:e"]
    assert ids(one) == ["pivocena:a:burza", "pivocena:m:burza", "pivocena:e:burza", "pivocena:p:e"]
    assert ids(two) == ["pivocena:a:burza", "pivocena:m:burza", "pivocena:e:burza", "pivocena:v:burza", "pivocena:p:e"]
    revert = two.children[3].item
    assert [o.label for o in revert.options] == ["Plzeň 12° · 59 Kč"]
    assert revert.options[0].description.endswith("· ➕ Plzeň 12° · 59 Kč")


def test_many_kinds_and_cancel(monkeypatch):
    monkeypatch.setattr(venues, "beer_prices", {})

    async def go():
        async with memory_db() as db:
            client = SimpleNamespace(db=db)
            await _tap(client, 1, "Plzeň 12°", "59")
            many = await _many(client, 1, "70")
            text = venues.PUBS["burza"].beer_text
            cancelled = await _many(client, 1, "")
            return many, text, cancelled, venues.PUBS["burza"].beer_text

    many, text, cancelled, after = run(go())
    assert "🍻 Víc druhů: kolem **70 Kč**" in _shown(many)
    assert text.startswith("💰 víc druhů · ~70 Kč (")
    assert "🍻 zrušeno „víc druhů“" in cancelled["content"] and after.startswith("💰 Plzeň 12° · 59 Kč")


def test_stale_and_unknown_pub(monkeypatch):
    monkeypatch.setattr(venues, "beer_prices", {})

    async def go():
        async with memory_db() as db:
            client = SimpleNamespace(db=db)
            gone = Interaction(client)
            await with_values(cenapiva.TapSelect("burza"), "Plzeň 12°").callback(gone)
            unknown = Interaction(client)
            await cenapiva.ManyButton("zruseny_podnik").callback(unknown)
            return gone.last(), unknown.last()

    gone, unknown = run(go())
    assert gone["content"] == unknown["content"] == cenapiva.STALE


def test_map_offers_editing():
    shown = Interaction(SimpleNamespace())
    run(napivo.MapButton().callback(shown))
    select = shown.last()["view"].children[0].item
    assert select.custom_id == "pivocena:p:n" and "burza" in [o.value for o in select.options]


def test_pub_select_shows_only_prices(monkeypatch):
    monkeypatch.setattr(venues, "beer_prices", {
        "burza": PubBeers(many_price=70, checked="11/2026"),
        "vlk": PubBeers((Tap("Plzeň 12°", 65),)),
        "palac": PubBeers((Tap("A", 45), Tap("B", 50), Tap("C", 70))),
    })
    options = {o.value: o.description for o in cenapiva.PubSelect("e").item.options}
    assert (options["burza"], options["vlk"], options["palac"]) == ("~70 Kč", "65 Kč", "~50 Kč")
    assert options["yacht"] == "cenu zatím nevíme"
    # výběr „Kam“ v /na-pivo: za adresou cena, u spočítané ceny i počet piv, u ručního „víc druhů“ jen cena
    places = {o.value: o.description for o in napivo.place_options(None)}
    assert places["vlk"] == "V centru · Zelný trh · 65 Kč" and places["burza"] == "V centru · Jánská 16 · ~70 Kč"
    assert places["palac"] == "V centru · Běhounská 18 · 3 piva · ~50 Kč"
    assert places["yacht"] == "U PPV · Kolejní 2 (koleje PPV)"


def test_pubs_by_area_matches_choices():
    keys = [p.key for p in venues.pubs_by_area()]
    assert sorted(keys) == sorted(venues.PUBS)
    assert [c.value for c in cenapiva.PUB_CHOICES] == keys[:25]
    assert [o.value for o in napivo.place_options(None) if o.value in venues.PUBS] == keys[:25 - len(venues.AREAS)]


def test_since_kept_for_unchanged_beers_and_after_revert():
    from datetime import datetime

    from lunch.service import TZ

    async def go():
        async with memory_db() as db:
            def at(day):
                return datetime(2026, 11, day, 18, 0, tzinfo=TZ)

            await beer.change(db, "burza", lambda s: beers.add(s, "Plzeň 12°", 59), 1, at(20))
            await beer.change(db, "burza", lambda s: beers.add(s, "Kozel 11°", 45), 1, at(21))
            first = (await beer.history(db, "burza"))[0]
            await beer.change(db, "burza", lambda s: beers.add(s, "Kozel 11°", 47, "Kozel 11°"), 1, at(22))
            edited = (await beer.history(db, "burza"))[0]
            await beer.revert(db, first, 2, at(23))
            reverted = (await beer.history(db, "burza"))[0]
            return first, edited, reverted

    first, edited, reverted = run(go())
    since = {v: {t.name: t.since.day for t in v.state.taps} for v in (first, edited, reverted)}
    assert since[first] == {"Kozel 11°": 21, "Plzeň 12°": 20}
    assert since[edited] == {"Kozel 11°": 22, "Plzeň 12°": 20}  # nová cena = nové datum, Plzeň beze změny
    assert since[reverted] == {"Kozel 11°": 21, "Plzeň 12°": 20}  # vrácená cena platí od původního data


def test_profile_buttons_survive_restart():
    async def go():
        items = []
        for cls, custom_id in [(cenapiva.AddButton, "pivocena:a:burza"), (cenapiva.RevertSelect, "pivocena:v:vlk")]:
            match = cls.__discord_ui_compiled_template__.fullmatch(custom_id)
            items.append(await cls.from_custom_id(None, None, match))
        return items

    add, revert = run(go())
    assert isinstance(add, cenapiva.AddButton) and add.pub_key == "burza"
    assert isinstance(revert, cenapiva.RevertSelect) and revert.pub_key == "vlk"


def test_profile_of_pub_with_many_beers(monkeypatch):
    monkeypatch.setattr(venues, "beer_prices", {})

    async def go():
        async with memory_db() as db:
            client = SimpleNamespace(db=db)
            for i in range(6):
                await _tap(client, 1, f"Pivo {i}", str(40 + i * 5))
            return await cenapiva.profile(db, "burza"), venues.PUBS["burza"].beer_text

    shown, listed = run(go())
    text = _shown(shown)
    assert "🍺 Točí **6 piv** · 40–65 Kč" in text and all(f"🍺 Pivo {i}" in text for i in range(6))
    assert listed.startswith("💰 6 piv · ~52 Kč")  # ve výpisech jen počet a medián
    assert len([f for f in shown["embed"].fields if f.inline]) % 3 == 0  # mřížka po třech
