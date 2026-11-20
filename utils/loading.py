"""Přehled o načítání dat na pozadí: log "hotovo" a ⏳ ve statusu bota, když to trvá déle.

Použití v obnově na pozadí:

    async with loading.track(self.bot, "slevy"):
        await self.shops.refresh_all()

- Po startu se zaloguje každý zdroj ("✅ Načteno: slevy za 38.2 s") a jednou i souhrn, až je všechno hotové.
- Později se logují jen pomalé obnovy (ostatní na úrovni DEBUG, ať log nezahlcují výluky každých 5 minut).
- Když načítání trvá déle než SHOW_AFTER sekund, bot to ukáže ve statusu (⏳). Rychlé obnovy status neblikají.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable

log = logging.getLogger("bot.loading")

SHOW_AFTER = 2.0  # s – kratší načítání se ve statusu neukazuje
SLOW = 2.0  # s – pomalejší obnovy se logují i po startu


class LoadingTracker:
    def __init__(self, on_change: Callable[[], Awaitable[None]] | None = None, show_after: float = SHOW_AFTER) -> None:
        self.on_change = on_change
        self.show_after = show_after
        self.active: dict[str, float] = {}  # zdroj -> začátek (monotonic)
        self.expected: set[str] = set()  # zdroje, které se načítají po startu
        self.done_once: set[str] = set()
        self.started = time.monotonic()
        self.startup_done = False
        self.sealed = False  # všechny zdroje už se zaregistrovaly (bot načetl všechny cogy)
        self.showing = False  # je teď ve statusu ⏳?

    def expect(self, name: str) -> None:
        """Zdroj, na který se čeká při startu (kvůli souhrnu "všechno načteno")."""
        self.expected.add(name)

    def seal(self) -> None:
        """Volá bot po načtení všech cogů: od teď se ví, na co všechno se po startu čeká."""
        self.sealed = True
        self._check_startup()

    def skip(self, name: str) -> None:
        """Zdroj se teď nenačítá (např. jídelníčky v noci) – pro souhrn po startu se bere jako hotový."""
        if name not in self.done_once:
            log.info("⏭️ Přeskočeno: %s (teď se nestahuje)", name)
        self._finished(name)

    @contextlib.asynccontextmanager
    async def track(self, name: str) -> AsyncIterator[None]:
        start = time.monotonic()
        self.active[name] = start
        reveal = asyncio.create_task(self._reveal_later())
        ok = False
        try:
            yield
            ok = True
        finally:
            reveal.cancel()
            del self.active[name]
            elapsed = time.monotonic() - start
            first = name not in self.done_once
            level = logging.INFO if first or elapsed >= SLOW or not ok else logging.DEBUG
            log.log(level, "%s %s za %.1f s", "✅ Načteno:" if ok else "⚠️ Nenačteno:", name, elapsed)
            self._finished(name)
            await self._update()

    def _finished(self, name: str) -> None:
        self.done_once.add(name)
        self._check_startup()

    def _check_startup(self) -> None:
        if not self.startup_done and self.sealed and self.expected and self.expected <= self.done_once:
            self.startup_done = True
            log.info("🚀 Všechna data po startu načtena za %.1f s", time.monotonic() - self.started)

    @property
    def busy(self) -> bool:
        """Běží načítání déle než show_after?"""
        now = time.monotonic()
        return any(now - start >= self.show_after for start in self.active.values())

    async def _reveal_later(self) -> None:
        await asyncio.sleep(self.show_after)
        await self._update()

    async def _update(self) -> None:
        busy = self.busy
        if busy != self.showing:
            self.showing = busy
            if self.on_change is not None:
                try:
                    await self.on_change()
                except Exception:  # status je jen kosmetika, nesmí shodit načítání
                    log.exception("Změna statusu selhala")


def track(bot, name: str):
    """`async with loading.track(bot, "slevy"):` – funguje i bez trackeru (testy, SimpleNamespace)."""
    tracker = getattr(bot, "loading", None)
    return tracker.track(name) if tracker is not None else contextlib.nullcontext()


def expect(bot, name: str) -> None:
    tracker = getattr(bot, "loading", None)
    if tracker is not None:
        tracker.expect(name)


def skip(bot, name: str) -> None:
    tracker = getattr(bot, "loading", None)
    if tracker is not None:
        tracker.skip(name)
