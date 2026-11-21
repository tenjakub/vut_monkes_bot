"""/na-pivo a /na-pivo-termin: stav se čte z embedu a zase do něj zapisuje, výběr termínu a podniků."""

from datetime import date, datetime

import discord

from cogs import napivo
from lunch.service import TZ
from pubs import planning, venues
from utils import render

CREATED = datetime(2026, 11, 21, 14, 5, tzinfo=TZ)  # sobota
TODAY = CREATED.date()


def via_discord(embed: discord.Embed) -> discord.Embed:
    """Embed tak, jak ho bot dostane zpátky od Discordu (timestamp jako text, UTC)."""
    return discord.Embed.from_dict(embed.to_dict())


def custom_ids(view: discord.ui.View) -> list[str]:
    return [i.item.custom_id for i in view.children]


def check_layout(view: discord.ui.View) -> None:
    ids = custom_ids(view)
    assert len(ids) == len(set(ids)) and len(ids) <= 25
    rows: dict[int, int] = {}
    for i in view.children:
        width = 5 if isinstance(i.item, discord.ui.Select) else 1  # výběr zabere celou řadu
        rows[i.item.row] = rows.get(i.item.row, 0) + width
    assert all(w <= 5 for w in rows.values()) and max(rows) <= 4


# --- podniky -------------------------------------------------------------------------------------


def test_venues_fit_into_one_select():
    options = napivo.place_options(None)
    assert len(venues.AREAS) + len(venues.PUBS) == len(options) <= 25, "víc než 25 možností se do výběru nevejde"
    assert len({o.value for o in options}) == len(options)
    assert all(len(o.label) <= 100 and len(o.description or "") <= 100 for o in options)
    # nahoře pohromadě obecné možnosti (kamkoliv a oblasti), pod nimi podniky po oblastech
    values = [o.value for o in options]
    assert values[: len(venues.AREAS)] == list(venues.AREAS) and values[0] == "kamkoliv"
    assert values[len(venues.AREAS):] == [p.key for a in venues.AREAS for p in venues.pubs_in(a)]


def test_map_links():
    assert venues.PUBS["burza"].map.startswith("https://www.google.com/maps/search/?api=1&query=Pivn")
    assert "Brno" in venues.PUBS["mystika"].map  # bez adresy aspoň "Mystika, Brno"
    embed = napivo.map_embed()
    text = " ".join(f.value for f in embed.fields)
    assert all(p.map in text for p in venues.PUBS.values())


def test_map_embed_spreads_big_area_over_full_width():
    names = [f.name for f in napivo.map_embed().fields]
    # řada malých oblastí, pak centrum přes tři sloupce (nadpis jen nad prvním); "Kamkoliv" tu není
    assert names == ["🏘️ U PPV", "🏢 U Purkyní", "💻 U FITu", "🏙️ V centru", render.BLANK, render.BLANK]


def test_place_roundtrip_for_pub_area_and_none():
    for place in ("burza", "centrum", "kachnicka", "kamkoliv", None):
        m = napivo.Meetup(TODAY, CREATED, "42", place=place)
        assert napivo.read_meetup(via_discord(napivo.meetup_embed(m))).place == place


# --- /na-pivo ------------------------------------------------------------------------------------


def test_meetup_roundtrip_and_answers():
    m = napivo.Meetup(TODAY, CREATED, "42", "19:00", "vlk")
    m.apply(1, "jdu")
    m.apply(2, "jindy")
    m.apply(3, "jdu")
    m.apply(3, "nejdu")  # změna odpovědi
    m.apply(2, "jindy")  # druhé kliknutí = odhlášení
    assert m.answers == {1: "jdu", 3: "nejdu"}
    back = napivo.read_meetup(via_discord(napivo.meetup_embed(m)))
    assert back == m
    embed = napivo.meetup_embed(m)
    assert embed.title == "🍺 Na pivo – sobota 21. 11."
    assert [f.name for f in embed.fields] == ["✅ Jdou (1)", "📅 Šli by jindy (0)", "❌ Nejdou (1)"]


def test_meetup_without_time_and_old_embed():
    m = napivo.Meetup(TODAY, CREATED, "42")
    back = napivo.read_meetup(via_discord(napivo.meetup_embed(m)))
    assert back.time is None and back.place is None and back.answers == {}
    assert napivo.read_meetup(discord.Embed(title="🍺 Na pivo – sobota 21. 11.")) is None  # bez timestampu
    assert napivo.read_meetup(None) is None


def test_meetup_buttons():
    m = napivo.Meetup(TODAY, CREATED, "42", "19:00", "burza", {1: "jdu"})
    view = napivo.meetup_view(m)
    check_layout(view)
    ids = custom_ids(view)
    assert {"napivo:cas", "napivo:kam", "napivo:a:jdu", "napivo:mapa", "napivo:termin"} <= set(ids)
    labels = [i.item.label for i in view.children if isinstance(i.item, discord.ui.Button)]
    assert "Jdu · 1" in labels and "Nejdu" in labels
    time_select = next(i.item for i in view.children if i.item.custom_id == "napivo:cas")
    assert [o.label for o in time_select.options if o.default] == ["19:00"]
    assert len(time_select.options) <= 25


# --- /na-pivo-termin -----------------------------------------------------------------------------


def test_best_day():
    sat, sun, mon = date(2026, 11, 21), date(2026, 11, 22), date(2026, 11, 23)
    votes = {1: {sun: "18:00", mon: None}, 2: {sun: "19:00"}, 3: {sun: None, mon: "20:00"}}
    best = planning.best_day(votes, sat)
    assert (best.day, best.users, best.time) == (sun, [1, 2, 3], "19:00")
    assert planning.best_day({1: {sun: None}}, sat).time is None  # všichni kdykoliv
    assert planning.best_day({1: {sat: None, mon: None}}, sat).day == sat  # při shodě dřívější
    assert planning.best_day({1: {sat: None}}, sun) is None  # uplynulé dny se nepočítají
    assert planning.common_time(["9:00", "18:30", None]) == "18:30"


def test_resolve_date_over_new_year():
    assert planning.resolve_date(3, 1, date(2026, 12, 28)) == date(2027, 1, 3)
    assert planning.resolve_date(28, 12, date(2026, 12, 28)) == date(2026, 12, 28)


def test_plan_roundtrip_and_votes():
    p = napivo.Plan(CREATED, "42", "centrum")
    p.vote(1, date(2026, 11, 22), "18:00")
    p.vote(1, date(2026, 11, 25), "any")
    p.vote(2, date(2026, 11, 22), "20:00")
    p.vote(3, date(2026, 11, 30), "any")
    p.vote(3, date(2026, 11, 30), "x")  # nemůžu = zrušení dne
    assert set(p.votes) == {1, 2}
    embed = napivo.plan_embed(p, TODAY)
    assert embed.title == "🗓️ Kdy na pivo? 21. 11. – 4. 12."
    assert "🏆 **Zatím nejlíp:** neděle 22. 11. od 20:00 · 2 lidi" in embed.description
    real = [f for f in embed.fields if f.name != render.BLANK]
    assert [f.name for f in real] == ["🏆 Ne 22. 11. (2)", "St 25. 11. (1)"]
    assert real[0].value == "<@1> · od 18:00\n<@2> · od 20:00"
    back = napivo.read_plan(via_discord(embed))
    assert back.votes == p.votes and back.place == "centrum" and back.creator == "42"
    assert napivo.read_plan(via_discord(napivo.meetup_embed(napivo.Meetup(TODAY, CREATED, "42")))) is None


def test_plan_buttons():
    p = napivo.Plan(CREATED, "42")
    p.vote(1, date(2026, 11, 22), "any")
    view = napivo.plan_view(p, date(2026, 11, 22))  # o den později: sobota už je pryč
    check_layout(view)
    days = [i.item for i in view.children if i.item.custom_id.startswith("pivokdy:d:")]
    assert len(days) == planning.PLAN_DAYS
    assert days[0].disabled and days[0].label == "So 21."
    assert days[1].label == "Ne 22. · 1" and days[1].style == discord.ButtonStyle.success
    call = next(i.item for i in view.children if i.item.custom_id == "pivokdy:svolat")
    assert not call.disabled
    empty = napivo.plan_view(napivo.Plan(CREATED, "42"), TODAY)
    assert next(i.item for i in empty.children if i.item.custom_id == "pivokdy:svolat").disabled


def test_day_modal_preselects_current_choice():
    modal = napivo.DayModal(date(2026, 11, 22), "18:00", voted=True)
    assert [o.value for o in modal.choice.options if o.default] == ["18:00"]
    fresh = napivo.DayModal(date(2026, 11, 22), None, voted=False)
    assert not any(o.default for o in fresh.choice.options)
    assert len(modal.title) <= 45



# --- ceny piva (připravené, zatím vypnuté) -------------------------------------------------------


def test_beer_prices_hidden_until_switched_on(monkeypatch):
    import dataclasses

    many = dataclasses.replace(venues.PUBS["burza"], beer=venues.Beer(70, many=True, checked="11/2026"))
    one = dataclasses.replace(venues.PUBS["vlk"], beer=venues.Beer(65, "Plzeň 12°"))
    monkeypatch.setitem(venues.PUBS, "burza", many)
    monkeypatch.setitem(venues.PUBS, "vlk", one)

    monkeypatch.setattr(venues, "SHOW_BEER_PRICES", False)
    assert many.beer_text == "" and "Kč" not in " ".join(f.value for f in napivo.map_embed().fields)

    monkeypatch.setattr(venues, "SHOW_BEER_PRICES", True)
    assert many.beer_text == "🍻 víc druhů, kolem 70 Kč (11/2026)"
    assert one.beer_text == "🍺 Plzeň 12° · 65 Kč"
    assert napivo.place_lines("vlk")[1] == "-# 🍺 Plzeň 12° · 65 Kč"
    assert "-# 🍻 víc druhů, kolem 70 Kč (11/2026)" in " ".join(f.value for f in napivo.map_embed().fields)
    # řádek s cenou nesmí rozbít čtení místa z embedu
    m = napivo.Meetup(TODAY, CREATED, "42", place="vlk")
    assert napivo.read_meetup(via_discord(napivo.meetup_embed(m))).place == "vlk"
