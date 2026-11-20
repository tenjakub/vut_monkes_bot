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


def test_cards_continuing_first_terminating_last(tt):
    deps = tt.departures(tt.stops_named("Kolejní"), at(2026, 11, 20, 10, 0))
    cards = mhd._cards(deps)
    assert [c.name for c in cards] == ["🚌 72 ↪ jede dál", "🚌 72 → Technologický park"]
    assert cards[0].value.startswith("_přes Technologický park_\n**10:03**")
    assert cards[1].value.startswith("🛑")


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
