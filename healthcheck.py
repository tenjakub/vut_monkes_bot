"""Docker healthcheck: bot je zdravý, pokud v poslední době obnovil heartbeat soubor.

Bot ho obnovuje každých 30 s, ale jen když je opravdu připojený k Discordu
(viz ObedBot.heartbeat v bot.py). Exit code 0 = zdravý, 1 = nezdravý.
"""

import os
import sys
import time

HEALTH_FILE = os.environ.get("HEALTH_FILE", "/tmp/vut_monkes_bot.heartbeat")
MAX_AGE = 120  # s

try:
    age = time.time() - os.stat(HEALTH_FILE).st_mtime
except FileNotFoundError:
    print("heartbeat zatím neexistuje")
    sys.exit(1)

print(f"heartbeat před {age:.0f} s")
sys.exit(0 if age < MAX_AGE else 1)
