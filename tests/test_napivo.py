"""/na-pivo a /na-pivo-termin: stav se čte z embedu a zase do něj zapisuje, výběr termínu a podniků."""

from datetime import date, datetime

import discord

from cogs import napivo
from lunch.service import TZ
from pubs import planning, venues
from utils import render
from utils.interactions import MessageState

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


# --- počasí u dnů (z uložené předpovědi Open-Meteo, 20. 11. 2026 večer) ---------------------------


def _weather():
    from pathlib import Path

    from weather import openmeteo

    return openmeteo.parse((Path(__file__).parent / "fixtures" / "openmeteo.json").read_text(encoding="utf-8"))


def test_plan_shows_evening_weather_on_days():
    from types import SimpleNamespace

    from weather import openmeteo

    weather = _weather()
    created = datetime(2026, 11, 20, 20, 50, tzinfo=TZ)
    p = napivo.Plan(created, "42")
    p.vote(1, date(2026, 11, 21), "19:00")
    view = napivo.plan_view(p, created.date(), weather)
    emojis = {i.item.custom_id: i.item.emoji for i in view.children if i.item.custom_id.startswith("pivokdy:d:")}
    expected = openmeteo.outlook(weather, date(2026, 11, 21)).icon
    assert str(emojis["pivokdy:d:20261121"]) == expected
    assert emojis["pivokdy:d:20261125"] is None  # tak daleko předpověď v uložených datech není
    embed = napivo.plan_embed(p, created.date(), weather)
    assert "(od 19:00)" in embed.description and embed.footer.text.endswith("Open-Meteo.com")
    # bez předpovědi v cache se počasí jen neukáže
    client = SimpleNamespace(fetcher=SimpleNamespace(peek=lambda url: None))
    msg = napivo.plan_message(p, client)
    assert msg["embed"].footer.text == "Založeno"
    assert napivo.read_plan(via_discord(embed)).votes == p.votes  # řádek s počasím nevadí čtení stavu


def test_meetup_weather_at_chosen_time():
    weather = _weather()
    m = napivo.Meetup(date(2026, 11, 21), datetime(2026, 11, 20, 21, 0, tzinfo=TZ), "42", "20:00", "vlk")
    embed = napivo.meetup_embed(m, weather)
    assert "(od 20:00)" in embed.description
    assert napivo.read_meetup(via_discord(embed)) == m


# --- událost na serveru --------------------------------------------------------------------------

EVENT_URL = "https://discord.com/events/111/222"


def test_event_link_roundtrip():
    m = napivo.Meetup(TODAY, CREATED, "42", "19:00", "vlk", {1: "jdu"}, event=EVENT_URL)
    back = napivo.read_meetup(via_discord(napivo.meetup_embed(m)))
    assert back.event == EVENT_URL and back.event_id == 222
    assert "📅 [Událost na serveru]" in napivo.meetup_embed(m).description
    without = napivo.meetup_embed(napivo.Meetup(TODAY, CREATED, "42"))
    assert "bot založí na serveru událost" in without.description


def test_wants_event():
    now = CREATED.replace(hour=15)
    m = napivo.Meetup(TODAY, CREATED, "42", "19:00", "vlk", {1: "jdu", 2: "jdu", 3: "jindy"})
    assert not m.wants_event(now)  # jdou jen 2
    m.apply(3, "jdu")
    assert m.wants_event(now)
    assert not m.wants_event(CREATED.replace(hour=19, minute=30))  # už začalo
    assert not napivo.Meetup(TODAY, CREATED, "42", None, None, dict(m.answers)).wants_event(now)  # bez času
    assert not napivo.Meetup(TODAY, CREATED, "42", "19:00", None, dict(m.answers), event=EVENT_URL).wants_event(now)


def test_event_name_and_location():
    pub = napivo.Meetup(TODAY, CREATED, "42", "19:00", "burza")
    assert napivo.event_name(pub) == "🍺 Na pivo – Pivní burza"
    assert napivo.event_location(pub).startswith("Pivní burza, ")
    area = napivo.Meetup(TODAY, CREATED, "42", "19:00", "centrum")
    assert napivo.event_name(area) == "🍺 Na pivo – v centru"
    assert napivo.event_name(napivo.Meetup(TODAY, CREATED, "42", "19:00", "kamkoliv")) == "🍺 Na pivo"
    fields = napivo._event_fields(pub)
    assert fields["start_time"] == CREATED.replace(hour=19, minute=0)
    assert fields["end_time"] - fields["start_time"] == napivo.timedelta(hours=napivo.EVENT_HOURS)


class _Event:
    def __init__(self, id_):
        self.id = id_
        self.url = f"https://discord.com/events/111/{id_}"
        self.edits = []

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class _Guild:
    id = 111

    def __init__(self):
        self.created: list[dict] = []
        self.events: dict[int, _Event] = {}

    async def create_scheduled_event(self, **kwargs):
        self.created.append(kwargs)
        event = _Event(200 + len(self.created))
        self.events[event.id] = event
        return event

    async def fetch_scheduled_event(self, id_):
        return self.events[id_]


class _Response:
    def __init__(self, inter):
        self.inter = inter

    async def edit_message(self, embed, view):
        self.inter.message.embeds = [via_discord(embed)]

    async def send_message(self, *a, **k):
        raise AssertionError(a)


class _Interaction:
    """Kliknutí: `message` je snímek zprávy v okamžiku kliknutí (jako u Discordu)."""

    def __init__(self, message, guild, user_id, can_create=True):
        self.message = message
        self.guild = guild
        self.user = type("U", (), {"id": user_id})()
        self.client = object()
        self.app_permissions = discord.Permissions(create_events=can_create)
        self.response = _Response(self)

    async def edit_original_response(self, embed, view):
        self.message.embeds = [via_discord(embed)]


class _Message:
    def __init__(self, id_, embed):
        self.id = id_
        self.embeds = [via_discord(embed)]
        self.jump_url = "https://discord.com/channels/111/5/6"

    def snapshot(self):
        copy = _Message(self.id, self.embeds[0])
        copy.embeds = list(self.embeds)
        return copy


def _click(message, guild, user, answer="jdu", can_create=True):
    import asyncio

    inter = _Interaction(message, guild, user, can_create)

    def change(m):
        m.apply(user, answer)

    asyncio.run(napivo._edit(inter, change))
    return inter.message


def test_third_going_creates_event_once(monkeypatch):
    monkeypatch.setattr(napivo, "_now", lambda: CREATED.replace(hour=15))
    monkeypatch.setattr(napivo, "_state", MessageState())
    guild = _Guild()
    msg = _Message(1, napivo.meetup_embed(napivo.Meetup(TODAY, CREATED, "42", "19:00", "vlk")))
    stale = msg.snapshot()  # někdo kliknul dřív, než se zpráva u něj obnovila
    msg = _click(msg, guild, 1)
    msg = _click(msg, guild, 2)
    assert guild.created == []
    msg = _click(msg, guild, 3)
    assert len(guild.created) == 1 and guild.created[0]["name"] == "🍺 Na pivo – U Dřevěného vlka"
    assert guild.created[0]["description"].endswith(msg.jump_url)
    assert "📅 [Událost na serveru](https://discord.com/events/111/201)" in msg.embeds[0].description
    # čtvrté kliknutí ze starého snímku zprávy: stav se vezme z posledního zápisu, druhá událost nevznikne
    _click(stale, guild, 4)
    assert len(guild.created) == 1
    back = napivo.read_meetup(napivo._state._embeds[1])
    assert set(back.answers) == {1, 2, 3, 4} and back.event_id == 201


def test_time_change_moves_event(monkeypatch):
    import asyncio

    monkeypatch.setattr(napivo, "_now", lambda: CREATED.replace(hour=15))
    monkeypatch.setattr(napivo, "_state", MessageState())
    guild = _Guild()
    event = _Event(222)
    guild.events[222] = event
    m = napivo.Meetup(TODAY, CREATED, "42", "19:00", "vlk", {1: "jdu", 2: "jdu", 3: "jdu"}, event=EVENT_URL)
    inter = _Interaction(_Message(2, napivo.meetup_embed(m)), guild, 1)

    def change(state):
        state.time = "20:30"

    asyncio.run(napivo._edit(inter, change))
    assert guild.created == [] and len(event.edits) == 1
    assert event.edits[0]["start_time"] == CREATED.replace(hour=20, minute=30)


def test_no_event_without_permission(monkeypatch):
    monkeypatch.setattr(napivo, "_now", lambda: CREATED.replace(hour=15))
    monkeypatch.setattr(napivo, "_state", MessageState())
    guild = _Guild()
    m = napivo.Meetup(TODAY, CREATED, "42", "19:00", "vlk", {1: "jdu", 2: "jdu"})
    msg = _click(_Message(3, napivo.meetup_embed(m)), guild, 3, can_create=False)
    assert guild.created == [] and "Událost na serveru" not in msg.embeds[0].description
