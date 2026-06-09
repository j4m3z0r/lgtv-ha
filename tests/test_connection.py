"""Standalone tests for connection.py recovery logic.

There is no pytest in this repo, so this is a self-contained asyncio script:
run ``python3 tests/test_connection.py`` and it prints PASS/FAIL per case and
exits non-zero on any failure.

connection.py only imports ``asyncio``/``logging`` and ``.const`` (which imports
nothing), so we can load it in isolation without pulling in Home Assistant. We
fabricate a minimal package namespace so its ``from .const import DOMAIN`` works.

These tests pin the post-fix contract: recovery must abandon a wedged/zombie
client and build a *fresh* one (never awaiting the zombie's uncancellable
``disconnect()``), swapping it into ``hass.data`` so callers and entities pick
it up. See the deadlock analysis in CLAUDE.md.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
COMP = os.path.join(HERE, "..", "custom_components", "lgtv_ha")

PKG = "lgtv_ha_under_test"


def _load():
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [os.path.abspath(COMP)]
    sys.modules[PKG] = pkg
    for name in ("const", "connection"):
        spec = importlib.util.spec_from_file_location(
            f"{PKG}.{name}", os.path.join(COMP, f"{name}.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"{PKG}.{name}"] = mod
        spec.loader.exec_module(mod)
    return sys.modules[f"{PKG}.connection"], sys.modules[f"{PKG}.const"]


conn, const = _load()
DOMAIN = const.DOMAIN


class _ConnClosed(Exception):
    """Stand-in for websockets ConnectionClosedOK."""


class FreshClient:
    """A healthy client a fresh connect() would produce."""

    def __init__(self):
        self.connected = False
        self.written = None

    def is_connected(self):
        return self.connected

    async def connect(self):
        self.connected = True

    async def get_power_state(self):
        return {"returnValue": True, "state": "Active"}

    async def set_settings(self, category, payload):
        self.written = (category, payload)
        return {"returnValue": True}


class ZombieClient:
    """is_connected() lies (True) but every request fails, and disconnect() is
    uncancellable — exactly like bscpylgtv on a dead socket."""

    def __init__(self):
        self.disconnect_called = False
        # A pending task standing in for bscpylgtv's connect_task.
        self.connect_task = asyncio.ensure_future(self._spin())

    async def _spin(self):
        await asyncio.Event().wait()  # never completes unless cancelled

    def is_connected(self):
        return True

    async def get_power_state(self):
        raise _ConnClosed("sent 1000 (OK); then received 1000 (OK)")

    async def set_settings(self, category, payload):
        raise _ConnClosed("sent 1000 (OK); then received 1000 (OK)")

    async def disconnect(self):
        # Mirror bscpylgtv: swallow cancellation forever. If recovery ever
        # awaits this, it deadlocks — which is the bug we are fixing.
        self.disconnect_called = True
        ev = asyncio.Event()
        while True:
            try:
                await asyncio.shield(ev.wait())
            except asyncio.CancelledError:
                pass


class FakeHass:
    def __init__(self):
        self.data = {}


def _make_entry(make_client):
    hass = FakeHass()
    eid = "entry1"
    # Build the initial client synchronously for setup convenience.
    first = make_client_sync_holder = None  # noqa: F841
    hass.data[DOMAIN] = {
        eid: {
            "lock": asyncio.Lock(),
            "make_client": make_client,
        }
    }
    return hass, eid


# ---- test cases ---------------------------------------------------------

async def test_healthy_call_uses_current_client():
    fresh = FreshClient()
    fresh.connected = True
    calls = []

    async def make_client():
        calls.append("made")
        return FreshClient()

    hass, eid = _make_entry(make_client)
    hass.data[DOMAIN][eid]["client"] = fresh

    result = await conn.async_guarded_call(
        hass, eid, lambda client: client.set_settings("picture", {"backlight": 42})
    )
    assert result == {"returnValue": True}, result
    assert fresh.written == ("picture", {"backlight": 42}), fresh.written
    assert calls == [], "healthy path must not build a new client"
    assert hass.data[DOMAIN][eid]["client"] is fresh


async def test_guarded_call_recovers_from_zombie_without_awaiting_disconnect():
    zombie = ZombieClient()
    built = []

    async def make_client():
        c = FreshClient()
        built.append(c)
        return c

    hass, eid = _make_entry(make_client)
    hass.data[DOMAIN][eid]["client"] = zombie

    # Must complete promptly; the zombie's disconnect() would hang forever.
    result = await asyncio.wait_for(
        conn.async_guarded_call(
            hass, eid, lambda client: client.set_settings("picture", {"backlight": 40})
        ),
        timeout=5,
    )
    assert result == {"returnValue": True}, result
    assert len(built) == 1, built
    new_client = built[0]
    assert hass.data[DOMAIN][eid]["client"] is new_client, "fresh client must be swapped in"
    assert new_client.written == ("picture", {"backlight": 40}), new_client.written
    assert new_client.is_connected()
    assert not zombie.disconnect_called, "recovery must NOT await the zombie's disconnect()"
    # The zombie's spin task must have been cancelled (abandoned), not leaked running.
    await asyncio.sleep(0)
    assert zombie.connect_task.cancelled() or zombie.connect_task.done(), "old connect_task must be abandoned"


async def test_health_check_recovers_zombie():
    zombie = ZombieClient()
    built = []

    async def make_client():
        c = FreshClient()
        built.append(c)
        return c

    hass, eid = _make_entry(make_client)
    hass.data[DOMAIN][eid]["client"] = zombie

    healthy = await asyncio.wait_for(conn.async_health_check(hass, eid), timeout=5)
    assert healthy is True
    assert hass.data[DOMAIN][eid]["client"] is built[0]
    assert not zombie.disconnect_called


async def test_health_check_healthy_noop():
    fresh = FreshClient()
    fresh.connected = True
    built = []

    async def make_client():
        built.append(1)
        return FreshClient()

    hass, eid = _make_entry(make_client)
    hass.data[DOMAIN][eid]["client"] = fresh

    healthy = await asyncio.wait_for(conn.async_health_check(hass, eid), timeout=5)
    assert healthy is True
    assert built == [], "healthy connection must not be reconnected"
    assert hass.data[DOMAIN][eid]["client"] is fresh


TESTS = [
    test_healthy_call_uses_current_client,
    test_guarded_call_recovers_from_zombie_without_awaiting_disconnect,
    test_health_check_recovers_zombie,
    test_health_check_healthy_noop,
]


async def _run():
    failures = 0
    for t in TESTS:
        try:
            await t()
        except Exception as ex:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {t.__name__}: {type(ex).__name__}: {ex}")
        else:
            print(f"PASS  {t.__name__}")
    return failures


def main():
    failures = asyncio.run(_run())
    if failures:
        print(f"\n{failures} test(s) failed")
        sys.exit(1)
    print("\nall tests passed")


if __name__ == "__main__":
    main()
