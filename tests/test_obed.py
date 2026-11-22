"""/obed: stav hlasování se čte z embedu a zase do něj zapisuje."""

from datetime import datetime

from cogs import obed
from lunch.service import TZ

NOW = datetime(2026, 11, 20, 11, 42, tzinfo=TZ)


def roundtrip(state, creator="42"):
    embed = obed.build_embed(state, creator)
    return obed.read_state(embed), obed.creator_of(embed)


def test_state_survives_embed_roundtrip():
    state = {1: ("stary_pivovar", "11:30"), 2: ("stary_pivovar", None), 3: ("lastrada", "🚶 11:42")}
    assert roundtrip(state) == (state, "42")
    assert roundtrip({}) == ({}, "42")


def test_apply_actions():
    state = {}
    assert obed.apply(state, 1, "t", "1130", NOW) == "Nejdřív vyber, kam jdeš. 🙂"  # čas bez místa
    obed.apply(state, 1, "p", "kolejni", NOW)
    obed.apply(state, 1, "t", "1130", NOW)
    assert state == {1: ("kolejni", "11:30")}
    obed.apply(state, 1, "p", "lastrada", NOW)  # změna místa, čas zůstává
    assert state == {1: ("lastrada", "11:30")}
    obed.apply(state, 1, "now", "", NOW)
    assert state == {1: ("lastrada", "🚶 11:42")}
    obed.apply(state, 1, "p", "lastrada", NOW)  # druhé kliknutí = odhlášení
    assert state == {}
    obed.apply(state, 2, "p", "kolejni", NOW)
    obed.apply(state, 2, "x", "", NOW)
    assert state == {}


def test_embed_lists_only_spots_with_people():
    embed = obed.build_embed({1: ("kolejni", "12:00"), 2: ("kolejni", "11:30")}, "42")
    real = [f for f in embed.fields if f.name != "​"]
    assert [f.name for f in real] == ["🏢 Kolejní (2)"]
    assert real[0].value == "<@2> · 11:30\n<@1> · 12:00"  # seřazeno podle času


def test_buttons():
    view = obed.build_view()
    ids = [i.item.custom_id for i in view.children]
    assert len(ids) == len(set(ids)) and len(ids) <= 25
    rows = [i.item.row for i in view.children]
    assert all(rows.count(r) <= 5 for r in set(rows))
    assert "obed:p:stary_pivovar" in ids and "obed:t:1130" in ids and "obed:now" in ids


class _Message:
    def __init__(self, embed, created):
        self.id = 7
        self.embeds = [embed]
        self.created_at = created


class _Response:
    def __init__(self, message):
        self.message = message

    async def edit_message(self, embed, view):
        self.message.embeds = [embed]

    async def send_message(self, *a, **k):
        raise AssertionError(a)


class _Interaction:
    def __init__(self, message, user):
        self.message = message
        self.user = type("U", (), {"id": user})()
        self.response = _Response(message)


def _click(message, user, spot):
    import asyncio

    button = obed.ObedButton("p", spot)
    asyncio.run(button.callback(_Interaction(message, user)))


def test_click_keeps_poll_date_and_sees_previous_click():
    yesterday = datetime(2026, 11, 19, 10, 0, tzinfo=TZ)
    first = obed.build_embed({}, "42", yesterday.date())
    msg = _Message(first, yesterday)
    stale = _Message(first, yesterday)  # druhé kliknutí ze snímku zprávy před prvním
    _click(msg, 1, "kolejni")
    _click(stale, 2, "lastrada")
    final = stale.embeds[0]
    assert final.title.endswith("čtvrtek 19. 11.")  # ne dnešní datum
    assert obed.read_state(final) == {1: ("kolejni", None), 2: ("lastrada", None)}
