"""Testy jízdního řádu MHD nad malým syntetickým GTFS a parseru výluk."""

import zipfile
from datetime import date, datetime

import pytest
from google.transit import gtfs_realtime_pb2

from cogs import mhd
from transit import alerts, gtfs
from transit.gtfs import TZ

FILES = {
    "stops.txt": """stop_id,stop_name,location_type
K1,Kolejní,0
T3,Technologický park,0
T4,Technologický park,0
T1,Technologický park,0
X1,Řečkovice,0
""",
    "routes.txt": """route_id,route_short_name,route_type
L72,72,3
L12,12,0
""",
    "trips.txt": """route_id,service_id,trip_id,trip_headsign
L72,WD,a1,Technologický park
L72,WD,a2,Poliklinika Lesná
L72,WD,b1,Technologický park
L12,WD,c1,Komárov
L72,WD,n1,Technologický park
L72,EXTRA,e1,Technologický park
""",
    "stop_times.txt": """trip_id,arrival_time,departure_time,stop_id,stop_sequence
a1,10:00:00,10:00:00,X1,1
a1,10:03:00,10:03:00,K1,2
a1,10:05:00,10:05:00,T4,3
a2,10:08:00,10:08:00,T4,1
a2,10:20:00,10:20:00,X1,2
b1,10:10:00,10:10:00,X1,1
b1,10:13:00,10:13:00,K1,2
b1,10:15:00,10:15:00,T3,3
c1,10:02:00,10:02:00,T1,1
c1,10:30:00,10:30:00,X1,2
n1,24:00:00,24:00:00,X1,1
n1,24:10:00,24:10:00,K1,2
n1,24:12:00,24:12:00,T3,3
e1,11:00:00,11:00:00,X1,1
e1,11:03:00,11:03:00,K1,2
e1,11:05:00,11:05:00,T3,3
""",
    # WD = pondělí–pátek, ale 23. 11. 2026 zrušeno; EXTRA jen v sobotu 21. 11. 2026
    "calendar.txt": """service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date
WD,1,1,1,1,1,0,0,20261101,20261231
EXTRA,0,0,0,0,0,0,0,20261101,20261231
""",
    "calendar_dates.txt": """service_id,date,exception_type
WD,20261123,2
EXTRA,20261121,1
""",
}


@pytest.fixture(scope="module")
def tt(tmp_path_factory):
    path = tmp_path_factory.mktemp("gtfs") / "gtfs.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in FILES.items():
            zf.writestr(name, content)
    return gtfs.load(path, ["Kolejní", "Technologický park"])


def at(y, mo, d, h, mi):
    return datetime(y, mo, d, h, mi, tzinfo=TZ)


def test_continuation(tt):
    deps = tt.departures(tt.stops_named("Kolejní"), at(2026, 11, 20, 10, 0))
    assert [(d.when.strftime("%H:%M"), d.destination) for d in deps] == [
        ("10:03", "Poliklinika Lesná"),  # dojede na Z4 a do 5 min odtud pokračuje
        ("10:13", "Technologický park"),  # dojede na Z3, nic nenavazuje
    ]
    assert deps[0].continues_to == "Poliklinika Lesná" and deps[0].last_stop == "Technologický park"
    assert deps[1].continues_to is None


def test_arrival_at_terminus_is_not_departure(tt):
    deps = tt.departures(tt.stops_named("Technologický park"), at(2026, 11, 20, 10, 0))
    assert [(d.line, d.headsign) for d in deps] == [("12", "Komárov"), ("72", "Poliklinika Lesná")]


def test_route_type_filter(tt):
    deps = tt.departures(tt.stops_named("Technologický park"), at(2026, 11, 20, 10, 0), route_types=(0,))
    assert [d.line for d in deps] == ["12"]


def test_after_midnight_trip_from_previous_day(tt):
    deps = tt.departures(tt.stops_named("Kolejní"), at(2026, 11, 21, 0, 5))
    assert [d.when for d in deps] == [at(2026, 11, 21, 0, 10)]


def test_calendar_exceptions(tt):
    assert tt.departures(tt.stops_named("Kolejní"), at(2026, 11, 23, 10, 0)) == []  # zrušeno
    sat = tt.departures(tt.stops_named("Kolejní"), at(2026, 11, 21, 10, 30))
    assert [d.when.strftime("%H:%M") for d in sat] == ["11:03"]  # jen přidaný spoj
    assert tt.active_services(date(2026, 11, 22)) == set()


KOLEJNI = mhd.BOARDS["kolejni"]


def test_cards_continuing_first_terminating_last(tt):
    deps = tt.departures(tt.stops_named("Kolejní"), at(2026, 11, 20, 10, 0))
    generic = mhd.Board("x", "Kolejní", "🚌", 0)  # bez popisku směru
    cards = mhd._cards(deps, generic)
    assert [c.name for c in cards] == ["🚌 72 ↪ jede dál", "🚌 72 → Technologický park"]
    assert cards[0].value.startswith("_přes Technologický park_\n**10:03**")
    assert cards[1].value.startswith("🛑")


def test_continuing_direction_label_is_pinned_first(tt):
    deps = tt.departures(tt.stops_named("Kolejní"), at(2026, 11, 20, 10, 0))
    deps = [_dep("65", 0, "Řečkovice, hřbitov", "🚌")] + deps  # 65 jede dřív, i tak má být 72 první
    cards = mhd._cards(deps, KOLEJNI)
    assert [c.name for c in cards] == ["🚌 72 → Semilasso", "🚌 65", "🚌 72 → Technologický park"]
    assert "přes" not in cards[0].value


def test_board_embeds_have_unique_urls():
    # Discord by embedy se stejnou URL sloučil a jedna zastávka by zmizela
    urls = {mhd._board_embed(b, [], 1000).url for b in mhd.BOARDS.values()}
    assert len(urls) == len(mhd.BOARDS)


def _feed_with_alert() -> bytes:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    e = feed.entity.add(id="lockout_1")
    for line in ("72", "x72"):
        e.alert.informed_entity.add(route_id=line)
    e.alert.header_text.translation.add(text="Výluka", language="cs-CZ")
    e.alert.description_text.translation.add(text="Kolejní\nZastávka přesunuta. . Jede odklonem.", language="cs-CZ")
    return feed.SerializeToString()


def test_alert_parsing():
    parsed = alerts.parse(_feed_with_alert())
    assert parsed[0].lines == ("72", "x72")
    assert parsed[0].title == "Kolejní"
    assert parsed[0].text == "Zastávka přesunuta. Jede odklonem."
    assert alerts.for_lines(parsed, {"12"}) == []
    assert alerts.for_lines(parsed, {"12", "72"}) == parsed


def _dep(line, minute, headsign, emoji="🚋", continues_to=None, stop_id="T2"):
    return gtfs.Departure(
        when=at(2026, 11, 20, 9, minute), line=line, emoji=emoji, headsign=headsign,
        stop_id=stop_id, last_stop=headsign, continues_to=continues_to,
    )


def test_merge_layout_tram_direction_cards_with_line_on_every_row():
    board = mhd.BOARDS["cervinkova"]
    deps = [
        _dep("12", 1, "Komárov", stop_id="U1072Z2"),
        _dep("10", 4, "Konečného náměstí", stop_id="U1072Z2"),
        _dep("12", 5, "Technologický park", stop_id="U1072Z1"),
        _dep("4", 8, "Babická", stop_id="U1072Z2"),
    ]
    cards = mhd._cards(deps, board)
    assert [c.name for c in cards] == ["🚋 Tram → Centrum", "🚋 Tram → Technologický park"]
    rows = cards[0].value.split("\n")
    assert [r.rsplit(" · ", 1)[1] for r in rows] == ["`12`", "`10`", "`4`"]


def test_merge_layout_falls_back_to_usual_headsign():
    board = mhd.Board("x", "X", "🚋", 0, layout="merge")
    cards = mhd._cards([_dep("12", 1, "Komárov", stop_id="Z9")], board, lambda stop, line: "Komárov")
    assert cards[0].name == "🚋 Tram → Komárov"


def test_lines_layout_card_per_line():
    board = mhd.BOARDS["skacelova_vychod"]
    deps = [
        _dep("72", 2, "Královo Pole, nádraží", "🚌", stop_id="U1567Z6"),
        _dep("30", 3, "Klarisky", "🚎", stop_id="U1567Z6"),
        _dep("72", 6, "Poliklinika Lesná", "🚌", stop_id="U1567Z6"),
        _dep("72", 9, "Královo Pole, nádraží", "🚌", stop_id="U1567Z6"),
    ]
    cards = mhd._cards(deps, board)
    # seřazeno podle čísla linky, ne podle času
    assert [c.name for c in cards] == ["🚎 30 → Klarisky", "🚌 72 → Královo Pole, nádraží"]
    rows = cards[1].value.split("\n")
    assert rows[1].endswith("· `Poliklinika Lesná`") and "`" not in rows[0] + rows[2]
    # obvyklá konečná z celého jízdního řádu má přednost před tou nejčastější v příští hodině
    usual = lambda stop, line: "Areál Slatina" if line == "72" else None
    cards = mhd._cards(deps, board, usual)
    assert cards[1].name == "🚌 72 → Areál Slatina"
    assert cards[1].value.count("`") == 6  # všechny tři časy mají značku


def test_skacelova_split_by_platform():
    east, west = mhd.BOARDS["skacelova_vychod"], mhd.BOARDS["skacelova_zapad"]
    assert east.platforms and west.platforms and not set(east.platforms) & set(west.platforms)
    assert east.label != west.label


def test_merged_line_ignores_destination():
    deps = [_dep("65", 1, "Řečkovice, hřbitov", "🚌"), _dep("65", 11, "Řečkovice, nádraží", "🚌")]
    cards = mhd._cards(deps, KOLEJNI)
    assert [c.name for c in cards] == ["🚌 65"]
    assert cards[0].value.count("**") == 4  # dva časy, oba tučně


def test_every_area_and_board_has_buttons():
    for group in mhd.GROUPS:
        view = mhd.build_view(group)
        assert len(view.children) <= 10


def test_usual_headsign_uses_whole_timetable(tt):
    k1 = tt.stops_named("Kolejní")[0]
    assert tt.usual_headsign(k1, "72") == "Technologický park"
    assert tt.usual_headsign(k1, "99") is None



def test_connections_including_after_midnight(tt):
    origins, dests = tt.stops_named("Kolejní"), tt.stops_named("Technologický park")
    cons = tt.connections(origins, dests, at(2026, 11, 20, 10, 0), at(2026, 11, 20, 10, 30))
    assert [(c.departure.strftime("%H:%M"), c.arrival.strftime("%H:%M"), c.destination) for c in cons] == [
        ("10:03", "10:05", "Technologický park"),
        ("10:13", "10:15", "Technologický park"),
    ]
    # spoj ze služby pátku s časem 24:10 = sobota 0:10
    late = tt.connections(origins, dests, at(2026, 11, 20, 23, 50), at(2026, 11, 21, 4, 0))
    assert [c.departure for c in late] == [at(2026, 11, 21, 0, 10)]
    assert late[0].arrival == at(2026, 11, 21, 0, 12)


def test_home_embed_one_card_for_all_dorms():
    from datetime import timedelta
    from types import SimpleNamespace

    now = at(2026, 11, 20, 22, 30)

    def con(minutes, line, dest, ride=15, origin="Česká", early=0):
        """Spoj z České za `minutes`; early > 0 = stejná jízda o tolik minut dřív z Hlavního nádraží."""
        dep = now + timedelta(minutes=minutes - early)
        emoji = "🚌" if line.startswith("N") else "🚋"
        return gtfs.Connection(f"t{minutes}", dep, dep + timedelta(minutes=ride + early), line, emoji, origin, dest, 0)

    def both(minutes, line, dest, ride=15, early=6):
        return [con(minutes, line, dest, ride), con(minutes, line, dest, ride, "Hlavní nádraží", early)]

    by_dorm = {
        # 12 jede kolem obou kolejí, poslední tramvaj na Purkyňovy jede dřív než na PPV
        "Kolejní": [*both(12, "12", "Kolejní"), *both(25, "12", "Kolejní"), *both(33, "N99", "Kolejní", early=3),
                    con(63, "N99", "Kolejní"), con(93, "N99", "Kolejní", origin="Hlavní nádraží")],
        "Skácelova": both(12, "12", "Skácelova", 11),
    }
    fake = SimpleNamespace(
        stops_named=lambda name: [name],
        connections=lambda origins, dests, *a: [c for d in dests for c in by_dorm.get(d, [])],
    )
    trips, offsets = mhd.all_home_trips(fake, now)
    assert offsets == {"12": 6, "N99": 3}
    embed = mhd._home_embed(trips, offsets, now)
    text = embed.description
    assert embed.title == "🌙 Domů na koleje"
    assert text.startswith(
        "🚉 Časy jsou ze zastávky **Česká**. Ze zastávky Hlavní nádraží jede 🚋 12 o 6 min a 🚌 N99 o 3 min dřív."
    )
    assert "**22:42** · 🚋 12 → Purkyně 22:53 · PPV 22:57" in text  # stejný spoj jen jednou, jen z České
    assert text.count("22:36") == 0 and text.count("**22:42**") == 1
    assert "🌙 **Poslední denní spoje:**\n22:42 · 🚋 12 (Purkyně 22:53 · PPV 22:57)\n" \
           "22:55 · 🚋 12 (PPV 23:10)" in text
    assert "🦉 **Noční:** 23:03 N99 · 23:33 N99 · 0:03 N99 (Hlavní nádraží)" in text
    # po posledním denním spoji už jen noční – bez zdvojeného řádku 🦉
    night_only = mhd._home_embed([t for t in trips if t.night], offsets, now).description
    assert "Denní spoje už dnes nejedou" in night_only and "🦉" not in night_only
    assert "jede 🚌 N99 o 3 min dřív" in night_only  # rozdíl jen u linek, které ve výpisu jsou


def test_home_trips_only_trams_and_n99():
    from datetime import timedelta
    from types import SimpleNamespace

    now = at(2026, 11, 20, 22, 30)

    def con(minutes, line, route_type, origin="Česká"):
        dep = now + timedelta(minutes=minutes)
        return gtfs.Connection(f"{line}{minutes}", dep, dep + timedelta(minutes=15), line, "🚌", origin, "Skácelova",
                               route_type)

    fake = SimpleNamespace(
        stops_named=lambda name: [name],
        connections=lambda *a: [con(5, "12", 0), con(8, "67", 3), con(33, "N93", 3), con(33, "N99", 3)],
    )
    assert [c.line for c in mhd.home_trips(fake, "purkyne", now)] == ["12", "N99"]
