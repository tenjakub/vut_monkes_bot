"""Počasí z Open-Meteo (https://open-meteo.com, zdarma bez klíče, data pod CC BY 4.0 – uvádět zdroj)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

# FIT VUT, Božetěchova – koleje PPV i Purkyňovy jsou kousek (Královo Pole)
LATITUDE, LONGITUDE = 49.2266, 16.5965
PLACE = "Královo Pole"

URL = "https://api.open-meteo.com/v1/forecast?" + urlencode(
    {
        "latitude": LATITUDE,
        "longitude": LONGITUDE,
        "current": "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,is_day",
        "hourly": "temperature_2m,precipitation_probability,weather_code,is_day,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset,weather_code",
        "timezone": "Europe/Prague",
        "forecast_days": 16,  # /pocasi ukazuje dnes a zítra, /na-pivo-termin počasí na dva týdny
    }
)
SOURCE_URL = "https://open-meteo.com/"

# WMO kódy počasí -> (emoji, popis)
WEATHER: dict[int, tuple[str, str]] = {
    0: ("☀️", "jasno"),
    1: ("🌤️", "skoro jasno"),
    2: ("⛅", "polojasno"),
    3: ("☁️", "zataženo"),
    45: ("🌫️", "mlha"),
    48: ("🌫️", "mlha s námrazou"),
    51: ("🌦️", "slabé mrholení"),
    53: ("🌦️", "mrholení"),
    55: ("🌧️", "silné mrholení"),
    56: ("🧊", "mrznoucí mrholení"),
    57: ("🧊", "mrznoucí mrholení"),
    61: ("🌧️", "slabý déšť"),
    63: ("🌧️", "déšť"),
    65: ("🌧️", "silný déšť"),
    66: ("🧊", "mrznoucí déšť"),
    67: ("🧊", "mrznoucí déšť"),
    71: ("🌨️", "slabé sněžení"),
    73: ("🌨️", "sněžení"),
    75: ("❄️", "silné sněžení"),
    77: ("🌨️", "sněhová zrna"),
    80: ("🌦️", "přeháňky"),
    81: ("🌧️", "přeháňky"),
    82: ("⛈️", "silné přeháňky"),
    85: ("🌨️", "sněhové přeháňky"),
    86: ("🌨️", "sněhové přeháňky"),
    95: ("⛈️", "bouřka"),
    96: ("⛈️", "bouřka s kroupami"),
    99: ("⛈️", "bouřka s kroupami"),
}
_NIGHT = {0: "🌙", 1: "🌙"}  # jasno v noci
SNOW_CODES = {71, 73, 75, 77, 85, 86}


def describe(code: int, is_day: bool = True) -> tuple[str, str]:
    icon, text = WEATHER.get(code, ("🌡️", "neznámé počasí"))
    if not is_day and code in _NIGHT:
        icon = _NIGHT[code]
    return icon, text


@dataclass(frozen=True)
class Hour:
    time: datetime
    temperature: float
    rain_chance: int  # %
    code: int
    is_day: bool
    wind: float = 0.0  # km/h


@dataclass(frozen=True)
class Day:
    date: date
    t_min: float
    t_max: float
    rain_chance: int
    code: int
    sunrise: datetime
    sunset: datetime


@dataclass(frozen=True)
class Forecast:
    time: datetime
    temperature: float
    feels_like: float
    wind: float  # km/h
    code: int
    is_day: bool
    hours: list[Hour]  # od aktuální hodiny dál
    days: list[Day]  # dnes, zítra, … (16 dní)


def parse(text: str) -> Forecast:
    data = json.loads(text)
    cur, hourly, daily = data["current"], data["hourly"], data["daily"]
    now = datetime.fromisoformat(cur["time"])
    this_hour = now.replace(minute=0)
    hours = [
        Hour(
            time=datetime.fromisoformat(t),
            temperature=hourly["temperature_2m"][i],
            rain_chance=hourly["precipitation_probability"][i] or 0,
            code=hourly["weather_code"][i],
            is_day=bool(hourly["is_day"][i]),
            wind=(hourly.get("wind_speed_10m") or [0.0] * len(hourly["time"]))[i] or 0.0,
        )
        for i, t in enumerate(hourly["time"])
        if datetime.fromisoformat(t) >= this_hour
    ]
    days = [
        Day(
            date=date.fromisoformat(d),
            t_min=daily["temperature_2m_min"][i],
            t_max=daily["temperature_2m_max"][i],
            rain_chance=daily["precipitation_probability_max"][i] or 0,
            code=daily["weather_code"][i],
            sunrise=datetime.fromisoformat(daily["sunrise"][i]),
            sunset=datetime.fromisoformat(daily["sunset"][i]),
        )
        for i, d in enumerate(daily["time"])
    ]
    return Forecast(
        time=now,
        temperature=cur["temperature_2m"],
        feels_like=cur["apparent_temperature"],
        wind=cur["wind_speed_10m"],
        code=cur["weather_code"],
        is_day=bool(cur["is_day"]),
        hours=hours,
        days=days,
    )


@dataclass(frozen=True)
class Outlook:
    """Počasí na pár hodin (třeba na večer v hospodě)."""

    icon: str
    text: str
    temperature: float  # průměr
    rain_chance: int  # max %

    def line(self) -> str:
        """'🌧️ déšť · 6 °C · 💧 60 %'"""
        rain = f" · 💧 {self.rain_chance} %" if self.rain_chance else ""
        return f"{self.icon} {self.text} · {round(self.temperature)} °C".replace("-", "−") + rain


EVENING_HOUR = 18  # „večer“ = od 18:00 na OUTLOOK_HOURS hodin


def _severity(code: int) -> int:
    return 3 if code in (45, 48) else code  # mlha není horší než déšť; jinak vyšší WMO kód = horší počasí


def outlook(f: Forecast, day: date, start_hour: int = EVENING_HOUR, hours: int = 4) -> Outlook | None:
    """Počasí v daný den od `start_hour` na `hours` hodin: nejhorší počasí, průměrná teplota, max šance na déšť.
    None, když předpověď na ty hodiny není (moc daleko, nebo už uplynuly)."""
    window = [h for h in f.hours if h.time.date() == day and start_hour <= h.time.hour < start_hour + hours]
    if not window:
        return None
    worst = max(window, key=lambda h: _severity(h.code))
    icon, text = describe(worst.code, worst.is_day)
    return Outlook(icon, text, sum(h.temperature for h in window) / len(window), max(h.rain_chance for h in window))


def advice(f: Forecast, horizon: int = 12) -> list[str]:
    """Krátké rady na příštích pár hodin (deštník, bunda…)."""
    soon = f.hours[:horizon]
    tips = []
    if any(h.code in SNOW_CODES for h in soon):
        tips.append("❄️ bude sněžit")
    rain = max((h.rain_chance for h in soon), default=0)
    if rain >= 50 and not any(h.code in SNOW_CODES for h in soon):
        tips.append(f"☂️ vem si deštník (déšť až {rain} %)")
    coldest = min([h.temperature for h in soon] + [f.feels_like], default=f.feels_like)
    if coldest <= 0:
        tips.append("🧤 mrzne, rukavice a čepice")
    elif coldest <= 10:
        tips.append("🧥 bunda")
    if max((h.temperature for h in soon), default=f.temperature) >= 27:
        tips.append("🥵 vedro, vem si vodu")
    if f.wind >= 40:
        tips.append("💨 hodně fouká")
    return tips


WINDOW_FROM_HOUR = 21  # od kolika večer radit s oknem
MORNING_HOUR = 7


def window_advice(f: Forecast) -> str | None:
    """Večer (po 21:00, a v noci do 4:00): nechat přes noc otevřené okno? Hlavně jestli nepromrznu a nenaprší dovnitř."""
    hour = f.time.hour
    if not (hour >= WINDOW_FROM_HOUR or hour < 4):
        return None
    morning = f.time.replace(hour=MORNING_HOUR, minute=0)
    if hour >= MORNING_HOUR:
        morning += timedelta(days=1)
    night = [h for h in f.hours if h.time <= morning]
    if not night:
        return None
    t_min = round(min(h.temperature for h in night))
    rain = max(h.rain_chance for h in night)
    wind = round(max(h.wind for h in night))
    t_text = f"{t_min} °C".replace("-", "−")
    if t_min <= 0:
        text = f"❄️ radši zavři, v noci mrzne (až {t_text})"
    elif rain >= 60:
        text = f"🌧️ zavři, nebo jen na ventilačku, v noci asi bude pršet ({rain} %)"
    elif t_min <= 5:
        text = f"🥶 jen na ventilačku, venku bude jen {t_text}"
    elif rain >= 30:
        text = f"🌦️ klidně na ventilačku, déšť není vyloučený ({rain} %), min {t_text}"
    else:
        text = f"✅ klidně nech otevřené, v noci min {t_text} a bez deště"
    if wind >= 40:
        text += f", fouká až {wind} km/h"
    return text
