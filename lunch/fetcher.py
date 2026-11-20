"""Stahování stránek s jednoduchou TTL cache, ať zbytečně nebombardujeme weby."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import aiohttp

log = logging.getLogger(__name__)

USER_AGENT = "Mozilla/5.0 (compatible; obed-discord-bot/1.0)"
# Ruční "Obnovit" stáhne stránku znovu jen pokud je cache starší než tohle.
FORCE_MIN_AGE = 60.0


@dataclass
class _Entry:
    text: str
    fetched: float  # time.monotonic()
    wall: float  # time.time(), pro zobrazení


class Fetcher:
    def __init__(self, timeout: float = 15.0) -> None:
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._session: aiohttp.ClientSession | None = None
        self._cache: dict[str, _Entry] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self._timeout, headers={"User-Agent": USER_AGENT}
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def get(self, url: str, ttl: float, force: bool = False) -> tuple[str, float]:
        """Vrátí (html, unix čas stažení). Paralelní dotazy na stejné URL se slijí."""
        lock = self._locks.setdefault(url, asyncio.Lock())
        async with lock:
            entry = self._cache.get(url)
            if entry is not None:
                age = time.monotonic() - entry.fetched
                max_age = FORCE_MIN_AGE if force else ttl
                if age < max_age:
                    return entry.text, entry.wall

            session = await self._get_session()
            log.info("GET %s", url)
            async with session.get(url) as resp:
                resp.raise_for_status()
                raw = await resp.read()
                charset = resp.charset or "utf-8"
            text = raw.decode(charset, errors="replace")
            entry = _Entry(text=text, fetched=time.monotonic(), wall=time.time())
            self._cache[url] = entry
            return entry.text, entry.wall
