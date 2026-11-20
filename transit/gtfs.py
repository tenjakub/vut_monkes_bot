"""Jízdní řád IDS JMK z GTFS (KORDIS, CC BY): https://kordis-jmk.cz/gtfs/gtfs.zip

Celý stop_times.txt má ~28 MB, takže si z něj při načtení necháváme jen:
- časy na zastávkách, které nás zajímají (podle názvu),
- první a poslední zastávku každého spoje (kvůli cíli a navazujícím spojům).

Navazující spoj: GTFS nemá block_id, takže "pokračování" odhadujeme. Spoj, který končí na
nástupišti P v čase A, pokračuje spojem stejné linky, který z téhož nástupiště P vyjíždí
v čase A … A + CONTINUATION_WINDOW. Na lince 72 na Technologickém parku to sedí přesně
(příjezd na Z4 = jede dál, příjezd na Z3 = končí).
"""

from __future__ import annotations

import bisect
import csv
import io
import zipfile
from collections import defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Prague")
CONTINUATION_WINDOW = 5 * 60  # s

ROUTE_EMOJI = {0: "🚋", 2: "🚆", 3: "🚌", 4: "⛴️", 11: "🚎", 800: "🚎"}
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


@dataclass(frozen=True)
class Route:
    line: str
    type: int

    @property
    def emoji(self) -> str:
        return ROUTE_EMOJI.get(self.type, "🚍")


@dataclass(frozen=True)
class Trip:
    route_id: str
    service_id: str
    headsign: str


@dataclass(frozen=True)
class Departure:
    when: datetime
    line: str
    emoji: str
    headsign: str  # cíl tohoto spoje
    stop_id: str  # nástupiště, ze kterého odjíždí
    last_stop: str  # název konečné tohoto spoje
    continues_to: str | None = None  # cíl navazujícího spoje, pokud vůz jede dál

    @property
    def destination(self) -> str:
        """Kam se tímhle vozem reálně dojede."""
        return self.continues_to or self.headsign


def _secs(t: str) -> int:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def _rows(zf: zipfile.ZipFile, name: str) -> Iterator[dict[str, str]]:
    with zf.open(name) as raw:
        yield from csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))


@dataclass
class Timetable:
    stop_names: dict[str, str]  # stop_id -> název (jen nástupiště, location_type 0)
    routes: dict[str, Route]
    trips: dict[str, Trip]
    calendar: dict[str, tuple[set[int], date, date]]  # service_id -> (dny v týdnu, od, do)
    exceptions: dict[date, dict[str, bool]]  # datum -> {service_id: přidáno/odebráno}
    # stop_id -> seřazený seznam (čas v s od půlnoci dne služby, trip_id); bez příjezdů na konečnou
    stop_index: dict[str, list[tuple[int, str]]]
    trip_end: dict[str, tuple[str, int]]  # trip_id -> (poslední nástupiště, čas příjezdu)
    # nástupiště -> seřazený seznam (odjezd z první zastávky, trip_id) – pro hledání navazujících spojů
    trip_starts: dict[str, list[tuple[int, str]]]
    created: datetime = field(default_factory=lambda: datetime.now(TZ))

    def stops_named(self, name: str) -> list[str]:
        return sorted(sid for sid, n in self.stop_names.items() if n == name)

    def active_services(self, day: date) -> set[str]:
        active = {
            sid
            for sid, (weekdays, start, end) in self.calendar.items()
            if start <= day <= end and day.weekday() in weekdays
        }
        for sid, added in self.exceptions.get(day, {}).items():
            (active.add if added else active.discard)(sid)
        return active

    def _continuation(self, trip_id: str, active: set[str]) -> str | None:
        end = self.trip_end.get(trip_id)
        if end is None:
            return None
        platform, arrival = end
        route_id = self.trips[trip_id].route_id
        starts = self.trip_starts.get(platform, [])
        i = bisect.bisect_left(starts, (arrival, ""))
        while i < len(starts) and starts[i][0] <= arrival + CONTINUATION_WINDOW:
            nxt = self.trips[starts[i][1]]
            if nxt.route_id == route_id and nxt.service_id in active and starts[i][1] != trip_id:
                return nxt.headsign
            i += 1
        return None

    def departures(
        self,
        stop_ids: Iterable[str],
        now: datetime,
        window: timedelta = timedelta(minutes=60),
        route_types: Iterable[int] | None = None,
    ) -> list[Departure]:
        allowed_types = set(route_types) if route_types is not None else None
        stop_ids = list(stop_ids)
        out: list[Departure] = []
        # dnešní spoje + včerejší, které jedou po půlnoci (časy 24:xx a víc)
        for offset in (0, -1):
            day = now.date() + timedelta(days=offset)
            active = self.active_services(day)
            midnight = datetime.combine(day, datetime.min.time(), TZ)
            lo = int((now - midnight).total_seconds())
            hi = lo + int(window.total_seconds())
            for sid in stop_ids:
                entries = self.stop_index.get(sid, [])
                i = bisect.bisect_left(entries, (lo, ""))
                for sec, trip_id in entries[i:]:
                    if sec > hi:
                        break
                    trip = self.trips[trip_id]
                    route = self.routes[trip.route_id]
                    if trip.service_id not in active:
                        continue
                    if allowed_types is not None and route.type not in allowed_types:
                        continue
                    end = self.trip_end.get(trip_id)
                    out.append(
                        Departure(
                            when=midnight + timedelta(seconds=sec),
                            line=route.line,
                            emoji=route.emoji,
                            headsign=trip.headsign,
                            stop_id=sid,
                            last_stop=self.stop_names.get(end[0], "") if end else "",
                            continues_to=self._continuation(trip_id, active),
                        )
                    )
        out.sort(key=lambda d: (d.when, d.line))
        return out


def load(path: Path, stop_names: Iterable[str]) -> Timetable:
    """Načte GTFS zip. Pomalé (~několik sekund), volat mimo event loop."""
    wanted_names = set(stop_names)
    with zipfile.ZipFile(path) as zf:
        stop_names_map: dict[str, str] = {}
        for r in _rows(zf, "stops.txt"):
            if r.get("location_type", "0") in ("", "0"):
                stop_names_map[r["stop_id"]] = r["stop_name"]
        targets = {sid for sid, n in stop_names_map.items() if n in wanted_names}

        routes = {
            r["route_id"]: Route(line=r["route_short_name"], type=int(r["route_type"] or 3))
            for r in _rows(zf, "routes.txt")
        }
        trips = {
            r["trip_id"]: Trip(r["route_id"], r["service_id"], r["trip_headsign"])
            for r in _rows(zf, "trips.txt")
        }

        calendar: dict[str, tuple[set[int], date, date]] = {}
        for r in _rows(zf, "calendar.txt"):
            days = {i for i, d in enumerate(WEEKDAYS) if r[d] == "1"}
            calendar[r["service_id"]] = (
                days,
                datetime.strptime(r["start_date"], "%Y%m%d").date(),
                datetime.strptime(r["end_date"], "%Y%m%d").date(),
            )
        exceptions: dict[date, dict[str, bool]] = defaultdict(dict)
        if "calendar_dates.txt" in zf.namelist():
            for r in _rows(zf, "calendar_dates.txt"):
                day = datetime.strptime(r["date"], "%Y%m%d").date()
                exceptions[day][r["service_id"]] = r["exception_type"] == "1"

        first: dict[str, tuple[int, str, int]] = {}  # trip -> (seq, stop, departure)
        last: dict[str, tuple[int, str, int]] = {}  # trip -> (seq, stop, arrival)
        at_targets: list[tuple[str, int, str, int]] = []  # (stop, seq, trip, departure)
        with zf.open("stop_times.txt") as raw:
            reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
            header = next(reader)
            i_trip, i_arr, i_dep = header.index("trip_id"), header.index("arrival_time"), header.index("departure_time")
            i_stop, i_seq = header.index("stop_id"), header.index("stop_sequence")
            for row in reader:
                trip_id, stop_id, seq = row[i_trip], row[i_stop], int(row[i_seq])
                f = first.get(trip_id)
                if f is None or seq < f[0]:
                    first[trip_id] = (seq, stop_id, _secs(row[i_dep]))
                lst = last.get(trip_id)
                if lst is None or seq > lst[0]:
                    last[trip_id] = (seq, stop_id, _secs(row[i_arr]))
                if stop_id in targets:
                    at_targets.append((stop_id, seq, trip_id, _secs(row[i_dep])))

    stop_index: dict[str, list[tuple[int, str]]] = defaultdict(list)
    relevant: set[str] = set()
    for stop_id, seq, trip_id, dep in at_targets:
        if trip_id in trips and seq != last[trip_id][0]:  # příjezd na konečnou není odjezd
            stop_index[stop_id].append((dep, trip_id))
            relevant.add(trip_id)
    for entries in stop_index.values():
        entries.sort()

    trip_end = {t: (last[t][1], last[t][2]) for t in relevant}
    end_platforms = {p for p, _ in trip_end.values()}
    trip_starts: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for trip_id, (_, stop_id, dep) in first.items():
        if stop_id in end_platforms and trip_id in trips:
            trip_starts[stop_id].append((dep, trip_id))
    for entries in trip_starts.values():
        entries.sort()

    return Timetable(
        stop_names=stop_names_map,
        routes=routes,
        trips=trips,
        calendar=calendar,
        exceptions=dict(exceptions),
        stop_index=dict(stop_index),
        trip_end=trip_end,
        trip_starts=dict(trip_starts),
    )
