"""Konfigurace z proměnných prostředí / souboru .env"""

import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "")
if not DISCORD_TOKEN:
    raise SystemExit("Chybí DISCORD_TOKEN – zkopíruj .env.example do .env a vyplň ho.")

# Volitelně: ID serverů (oddělená čárkou) pro okamžitou registraci slash commandů.
GUILD_IDS = [int(x) for x in os.environ.get("GUILD_IDS", "").replace(" ", "").split(",") if x]


def _git_version() -> str:
    """Lokálně (mimo Docker) zkusí zjistit krátký hash commitu, jinak "dev"."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        ).stdout.strip()
        return f"dev {sha}" if sha else "dev"
    except (OSError, subprocess.SubprocessError):
        return "dev"


# Verze = krátký hash commitu. Do Docker image ji doplní CI (stejný hash jako tag sha-…),
# lokálně se zjistí z gitu jako "dev <hash>".
BOT_VERSION = os.environ.get("BOT_VERSION") or _git_version()

REPO_URL = "https://github.com/tenjakub/vut_monkes_bot"
ISSUES_URL = f"{REPO_URL}/issues"

# Soubor, který bot pravidelně "dotýká", dokud je připojený – kontroluje ho healthcheck.py
HEALTH_FILE = os.environ.get("HEALTH_FILE", "/tmp/vut_monkes_bot.heartbeat")
