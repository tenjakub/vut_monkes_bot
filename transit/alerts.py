"""Výluky a omezení z GTFS Realtime feedu KORDIS: https://kordis-jmk.cz/gtfs/gtfsReal.dat

Feed obsahuje i polohy vozidel, ale jejich trip_id zatím nesedí na statický jízdní řád,
takže z něj bereme jen výluky (alerty). Ty jsou navázané na číslo linky (route_id = "72").
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from google.transit import gtfs_realtime_pb2

from lunch.models import norm

URL = "https://kordis-jmk.cz/gtfs/gtfsReal.dat"
LOCKOUTS_URL = "https://www.idsjmk.cz/lockouts/index"


@dataclass(frozen=True)
class Alert:
    id: str
    lines: tuple[str, ...]
    title: str
    text: str
    url: str | None = None


def _translation(ts: gtfs_realtime_pb2.TranslatedString) -> str:
    for t in ts.translation:
        if t.language.startswith("cs"):
            return t.text
    return ts.translation[0].text if ts.translation else ""


def parse(data: bytes) -> list[Alert]:
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(data)
    alerts: list[Alert] = []
    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue
        a = entity.alert
        lines = tuple(dict.fromkeys(ie.route_id for ie in a.informed_entity if ie.route_id))
        header = norm(_translation(a.header_text))
        description = _translation(a.description_text).strip()
        # popis bývá "Název výluky\nPodrobnosti…" – první řádek je lepší titulek než obecné "Výluka"
        first, _, rest = description.partition("\n")
        title = norm(first) if first and rest else header
        text = norm(rest if first and rest else description)
        text = re.sub(r"(\s*\.){2,}", ".", text)  # feed obsahuje artefakty typu ". ."
        url = _translation(a.url) or None
        alerts.append(Alert(entity.id, lines, title or header or "Výluka", text, url))
    return alerts


def for_lines(alerts: Iterable[Alert], lines: Iterable[str]) -> list[Alert]:
    wanted = set(lines)
    return [a for a in alerts if wanted.intersection(a.lines)]
