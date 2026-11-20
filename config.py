"""Konfigurace z proměnných prostředí / souboru .env"""

import os

from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
if not DISCORD_TOKEN:
    raise SystemExit("Chybí DISCORD_TOKEN – zkopíruj .env.example do .env a vyplň ho.")

# Volitelně: ID serverů (oddělená čárkou) pro okamžitou registraci slash commandů.
GUILD_IDS = [int(x) for x in os.environ.get("GUILD_IDS", "").replace(" ", "").split(",") if x]

# Verze (commit), do Docker image ji doplní CI. Lokálně "dev".
BOT_VERSION = os.environ.get("BOT_VERSION", "dev")

# Soubor, který bot pravidelně "dotýká", dokud je připojený – kontroluje ho healthcheck.py
HEALTH_FILE = os.environ.get("HEALTH_FILE", "/tmp/vut_monkes_bot.heartbeat")
