"""🍺 /cena-piva: zadání ceny okném, historie, vrácení nesmyslu a ceny v /na-pivo."""

import asyncio
from types import SimpleNamespace

import pytest

from cogs import cenapiva, napivo
from pubs import venues
from storage import beer
from tests.fakes import Interaction, memory_db, with_values


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(("text", "expected"), [("59", 59), (" 59 Kč", 59), ("59,-", 59), ("", None)])
def test_parse_price(text, expected):
    assert cenapiva.parse_price(text) == expected


@pytest.mark.parametrize("text", ["5", "9999", "levné", "59,50"])
def test_parse_price_nonsense(text):
    with pytest.raises(ValueError):
        cenapiva.parse_price(text)


async def _submit(client, user_id, price, name="", many=False):
    entries = await beer.history(client.db, "burza", limit=1)
    modal = cenapiva.PriceModal("burza", entries[0] if entries else None)
    modal.price._value, modal.beer._value = price, name
    modal.many._values = [cenapiva.MANY_YES if many else cenapiva.MANY_NO]
    interaction = Interaction(client, user_id=user_id)
    await modal.on_submit(interaction)
    return interaction.last()


def test_edit_history_and_revert(monkeypatch):
    monkeypatch.setattr(venues, "beer_prices", {})

    async def go():
        async with memory_db() as db:
            client = SimpleNamespace(db=db)
            cog = cenapiva.CenaPiva(client)
            opened = Interaction(client)
            await cog.cena_piva.callback(cog, opened)
            picked = Interaction(client)
            await with_values(cenapiva.PubSelect("e"), "burza").callback(picked)
            edit = Interaction(client)
            await cenapiva.EditButton("burza").callback(edit)
            saved = await _submit(client, 1, "59", "Plzeň 12°")
            in_napivo = napivo.place_lines("burza")
            vandal = await _submit(client, 2, "499", "zadarmo")
            bad = await _submit(client, 2, "hodně")
            first = (await beer.history(db, "burza"))[-1]
            back = Interaction(client, user_id=1)
            await with_values(cenapiva.RevertSelect("burza"), str(first.id)).callback(back)
            history = await beer.history(db, "burza")
            return (opened.last(), picked.last(), edit.response.calls[0], saved, in_napivo, vandal, bad,
                    back.last(), history, dict(venues.beer_prices))

    opened, picked, edit, saved, in_napivo, vandal, bad, back, history, cache = run(go())
    assert "**Pivní burza** — _nevíme_" in opened["content"] and opened["ephemeral"]
    assert "_Cenu zatím nikdo nezadal._" in picked["content"]
    assert edit[0] == "modal"
    assert saved["content"].startswith("✅ Uloženo, díky!") and "**Teď:** 💰 Plzeň 12° · 59 Kč" in saved["content"]
    assert in_napivo[1].startswith("-# 💰 Plzeň 12° · 59 Kč (")
    assert "**Teď:** 💰 zadarmo · 499 Kč" in vandal["content"]
    assert "nechápu" in bad["content"]
    assert back["content"].startswith("↩️ Vráceno na: 💰 Plzeň 12° · 59 Kč")
    assert "(vráceno) · <@1>" in back["content"] and "<@2>" in back["content"]  # kdo co zadal, je vidět
    assert [h.price for h in history] == [59, 499, 59] and history[0].reverted_from == history[-1].id
    assert cache["burza"].price == 59


def test_cleared_price_disappears_and_map_offers_editing(monkeypatch):
    monkeypatch.setattr(venues, "beer_prices", {})

    async def go():
        async with memory_db() as db:
            client = SimpleNamespace(db=db)
            await _submit(client, 1, "70", many=True)
            many = venues.PUBS["burza"].beer_text
            cleared = await _submit(client, 1, "")
            return many, cleared, venues.PUBS["burza"].beer_text

    many, cleared, after = run(go())
    assert many.startswith("💰 víc druhů · ~70 Kč")
    assert cleared["content"].startswith("🚫 Cena smazaná.") and after == ""

    shown = Interaction(SimpleNamespace())
    run(napivo.MapButton().callback(shown))
    select = shown.last()["view"].children[0].item
    assert select.custom_id == "pivocena:p:n" and "burza" in [o.value for o in select.options]


def test_pub_select_shows_only_prices(monkeypatch):
    monkeypatch.setattr(venues, "beer_prices", {
        "burza": venues.Beer(70, many=True, checked="11/2026"), "vlk": venues.Beer(65, "Plzeň 12°"),
    })
    options = {o.value: o.description for o in cenapiva.PubSelect("e").item.options}
    assert (options["burza"], options["vlk"], options["yacht"]) == ("~70 Kč", "65 Kč", "cenu zatím nevíme")
