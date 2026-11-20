"""Sledování načítání: log "načteno", souhrn po startu a ⏳ ve statusu jen u delšího načítání."""

import asyncio
import logging

import pytest

from utils.loading import LoadingTracker


def run(coro):
    return asyncio.run(coro)


def test_status_shows_only_for_slow_loads():
    changes = []

    async def scenario():
        tracker = LoadingTracker(show_after=0.05)

        async def on_change():
            changes.append(tracker.showing)

        tracker.on_change = on_change
        async with tracker.track("rychlé"):
            await asyncio.sleep(0.01)  # rychlé -> status se nemění
        assert changes == []
        async with tracker.track("pomalé"):
            await asyncio.sleep(0.12)
            assert tracker.showing  # během načítání ⏳
        assert not tracker.showing

    run(scenario())
    assert changes == [True, False]


def test_startup_summary_after_all_expected(caplog):
    async def scenario():
        tracker = LoadingTracker(show_after=10)
        tracker.expect("slevy")
        tracker.expect("menzy")
        async with tracker.track("slevy"):
            pass
        tracker.seal()  # registrace hotová, ale menzy ještě ne
        assert not tracker.startup_done
        tracker.skip("menzy")  # v noci se menzy nestahují
        assert tracker.startup_done

    with caplog.at_level(logging.INFO, logger="bot.loading"):
        run(scenario())
    messages = [r.getMessage() for r in caplog.records]
    assert any(m.startswith("✅ Načteno: slevy za") for m in messages)
    assert sum("Všechna data po startu načtena" in m for m in messages) == 1


def test_failed_load_is_logged_and_reraised(caplog):
    async def scenario():
        tracker = LoadingTracker(show_after=10)
        with pytest.raises(RuntimeError):
            async with tracker.track("počasí"):
                raise RuntimeError("výpadek")
        assert tracker.active == {}

    with caplog.at_level(logging.INFO, logger="bot.loading"):
        run(scenario())
    assert any(r.getMessage().startswith("⚠️ Nenačteno: počasí") for r in caplog.records)
