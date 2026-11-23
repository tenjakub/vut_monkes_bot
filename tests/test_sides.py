"""Hodnocení jídla bez přílohy: klíč jídla (lunch.sides) a souhrn přes přílohy a menzy (storage.ratings)."""

import asyncio
from datetime import datetime

import pytest

from lunch import kam, service
from lunch.models import Dish, Menu
from lunch.service import RESTAURANTS
from lunch.sides import pool, rating_key
from storage import menus as stored_menus
from storage import ratings
from tests.fakes import memory_db

NOW = datetime(2026, 11, 23, 11, 30, tzinfo=service.TZ)


# Skutečné názvy z KaM a restaurací (listopad 2026): příloha, tatarka ani gramáž v klíči nejsou.
@pytest.mark.parametrize(("name", "key"), [
    ("Smažený sýr, tatarská omáčka, Brambory americké", "smažený sýr"),
    ("Smažený sýr, tatarská omáčka", "smažený sýr"),
    ("Smažený hermelín, tatarská omáčka, Hranolky", "smažený hermelín"),
    ("Vepřový steak 200g, omáčka tatarská, Hranolky", "vepřový steak"),
    ("Vepřový steak 150g, slaninový chips, Rýže jasmínová", "vepřový steak slaninový chips"),
    ("Kuřecí plátek 150g s hermelínem a šunkou", "kuřecí plátek s hermelínem a šunkou"),
    ("Kuře po selsku, Bramborové halušky", "kuře po selsku"),
    ("Vepřové maso námořnické, Těstoviny", "vepřové maso námořnické"),
    ("Vepřové nudličky po mexicku, Brambory maštěné máslem", "vepřové nudličky po mexicku"),
    ("Kuřecí steak 150g, jogurt.om.s baklažány", "kuřecí steak jogurt om s baklažány"),
    ("Rizoto srbské, okurek", "rizoto srbské"),
    ("Bramborové knedlíky s uzeným masem, zelí", "bramborové knedlíky s uzeným masem zelí"),
    ("Kuskus s kuřecím masem a zeleninou", "kuskus s kuřecím masem a zeleninou"),
    ("Hovězí svíčková pečeně na smetaně s brusinkovým terčem, houskový knedlík",
     "hovězí svíčková pečeně na smetaně s brusinkovým terčem"),
    ("Smažená sýrová jehla, vařené brambory, tatarská omáčka", "smažená sýrová jehla"),
    ("200g Kuřecí řízky s vídeňským bramborovým salátem", "kuřecí řízky"),
    ("Vepřový steak s fazolky se slaninou, pepřová omáčka, americké brambory",
     "vepřový steak s fazolky se slaninou pepřová omáčka"),
    ("Kuřecí směs po lesnicku (anglická slanina, cibule, žampiony), dušená rýže", "kuřecí směs po lesnicku"),
    ("Smažený holandský řízek se sýrem, bramborová kaše s máslem, kyselý okurek", "smažený holandský řízek se sýrem"),
    ("BBQ Burger (Hovězí maso, karamelizovaná cibule, BBQ omáčka), hranolky a dresink", "bbq burger"),
    ("Čevabčiči s hořčicí a červenou cibulí, vařené brambory s petrželkou 🌾", "čevabčiči s hořčicí a červenou cibulí"),
    ("Hranolky", "hranolky"),  # samotná příloha zůstane, jinak by nebylo co hodnotit
])
def test_rating_key(name, key):
    assert rating_key(name) == key


def test_pools():
    assert pool("kolejni") == pool("q_technicka") == pool("purkynova")
    restaurant = RESTAURANTS[0].place.key
    assert pool(restaurant) == restaurant != pool("kolejni")


def test_summary_ignores_side_and_menza():
    def menu(place, day, *names):
        return Menu(place, [Dish(n, "100 Kč") for n in names], fetched_at=day)

    restaurant = RESTAURANTS[0].place
    tomorrow = NOW.replace(day=24)

    async def go():
        async with memory_db() as db:
            await stored_menus.record(db, [
                menu(kam.MENZY["kolejni"], NOW, "Smažený sýr, tatarská omáčka, Brambory americké"),
                menu(restaurant, NOW, "Smažený sýr, hranolky"),
            ], NOW)
            await stored_menus.record(db, [menu(kam.MENZY["q_technicka"], tomorrow, "Smažený sýr, tatarská omáčka")],
                                      tomorrow)
            dishes = {(d.place, d.day.day): d for d in await stored_menus.for_day(db, NOW.date(), ["kolejni"])}
            dishes |= {(d.place, d.day.day): d for d in await stored_menus.for_day(db, tomorrow.date(), ["q_technicka"])}
            await ratings.rate(db, dishes[("kolejni", 23)].id, 1, ratings.GOOD, NOW)
            await ratings.rate(db, dishes[("q_technicka", 24)].id, 2, ratings.BAD, tomorrow)
            return await ratings.summaries(db, [
                ("purkynova", "Smažený sýr, Hranolky"),  # jiná menza, jiná příloha
                (restaurant.key, "Smažený sýr, hranolky"),  # restaurace se s menzami nesčítá
                ("kolejni", "Smažený hermelín, tatarská omáčka"),  # jiné jídlo
            ])

    assert asyncio.run(go()) == {("purkynova", "Smažený sýr, Hranolky"): ratings.Summary(good=1, bad=1)}
