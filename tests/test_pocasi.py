"""Počasí: parser odpovědi Open-Meteo (uložená 20. 11. 2026 večer) a rady."""

from dataclasses import replace
from pathlib import Path

from cogs import pocasi
from weather import openmeteo

FIX = Path(__file__).parent / "fixtures" / "openmeteo.json"


def forecast():
    return openmeteo.parse(FIX.read_text(encoding="utf-8"))


def test_parse():
    f = forecast()
    assert f.temperature == 8.4 and not f.is_day
    assert f.hours[0].time.hour == 20  # od aktuální hodiny
    assert [d.date.isoformat() for d in f.days] == ["2026-11-20", "2026-11-21"]
    assert openmeteo.describe(0, is_day=False)[0] == "🌙"
    assert openmeteo.describe(3) == ("☁️", "zataženo")


def test_advice():
    f = forecast()
    rainy = replace(f, hours=[replace(h, rain_chance=80, temperature=5) for h in f.hours])
    assert "☂️ vem si deštník (déšť až 80 %)" in openmeteo.advice(rainy)
    assert "🧥 bunda" in openmeteo.advice(rainy)
    frost = replace(f, feels_like=-3, hours=[replace(h, temperature=-1, rain_chance=0) for h in f.hours])
    assert openmeteo.advice(frost) == ["🧤 mrzne, rukavice a čepice"]
    snow = replace(f, hours=[replace(h, code=73, rain_chance=90) for h in f.hours])
    tips = openmeteo.advice(snow)
    assert "❄️ bude sněžit" in tips and not any("deštník" in t for t in tips)


def test_embed():
    embed = pocasi.weather_embed(forecast())
    assert embed.description.startswith("## ☁️ 8 °C")
    cards = [f for f in embed.fields if f.inline and f.name != "​"]
    assert len(cards) == 6 and cards[0].name == "🕐 23:00"
    assert embed.fields[-1].name == "📅 Dnes a zítra" and "🌅 7:11" in embed.fields[-1].value
    assert "Open-Meteo" in embed.footer.text
