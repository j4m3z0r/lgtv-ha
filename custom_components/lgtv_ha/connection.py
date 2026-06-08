"""Connection health/recovery helpers for the shared WebOsClient.

bscpylgtv's ``is_connected()`` only checks whether the internal connect task is
still pending — after the TV is powered off it can report ``True`` while the
underlying websocket is already dead (a "zombie" connection). Relying on it
alone means the background reconnect never fires and every command fails with
``ConnectionClosedOK``. These helpers instead probe the connection with a real,
timeout-bounded request and force a clean reconnect when it isn't actually alive.
"""
from __future__ import annotations

import asyncio
import logging

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PROBE_TIMEOUT = 5
RECONNECT_TIMEOUT = 15
# A zombie connection's disconnect() can hang forever (bscpylgtv awaits a
# close handshake the dead socket never completes). Bounding it ensures the
# health loop / reload can always proceed to a fresh connect instead of
# wedging the whole entry.
DISCONNECT_TIMEOUT = 8
# Every request to the TV must be bounded. bscpylgtv has no per-request
# timeout, so a request issued on a zombie socket (writable but dead) blocks
# forever instead of raising. Unbounded, that freezes entity polls, hangs the
# service call behind a slider/command, and — because the hang never raises —
# stops async_guarded_call from ever reaching its reconnect path, so the
# connection never self-heals. A blocked in-flight request also wedges entry
# unload in ``unload_in_progress``. Bounding turns all of that into a fast,
# recoverable failure.
COMMAND_TIMEOUT = 8
READ_TIMEOUT = 8


async def async_is_alive(client) -> bool:
    """Return True only if the connection actually responds to a request."""
    if not client.is_connected():
        return False
    try:
        await asyncio.wait_for(client.get_power_state(), timeout=PROBE_TIMEOUT)
        return True
    except Exception:  # noqa: BLE001 - any failure means the link is not usable
        return False


async def _async_force_reconnect(client) -> bool:
    """Tear down any (possibly zombie) connection and connect fresh.

    Callers must hold the per-entry lock.
    """
    try:
        await asyncio.wait_for(client.disconnect(), timeout=DISCONNECT_TIMEOUT)
    except Exception:  # noqa: BLE001 - a hung/zombie disconnect must not block the reconnect
        pass
    try:
        await asyncio.wait_for(client.connect(), timeout=RECONNECT_TIMEOUT)
    except Exception as ex:  # noqa: BLE001
        _LOGGER.debug("Reconnect failed: %s", ex)
        return False
    return client.is_connected()


async def async_health_check(hass, entry_id) -> bool:
    """Probe the connection and reconnect if it's down/zombie. Returns health."""
    data = hass.data[DOMAIN].get(entry_id)
    if data is None:
        return False
    client = data["client"]
    async with data["lock"]:
        if await async_is_alive(client):
            return True
        _LOGGER.debug("Connection not alive; forcing reconnect")
        return await _async_force_reconnect(client)


async def async_guarded_call(hass, entry_id, factory):
    """Run ``factory()``; on failure, force one reconnect and retry once.

    ``factory`` is a zero-arg callable returning the awaitable to run, so it can
    be re-invoked on the retry. Each attempt is bounded by ``COMMAND_TIMEOUT``:
    a request on a zombie socket would otherwise hang forever, so the timeout is
    what lets a stuck command both fail fast *and* drive the reconnect below.
    """
    data = hass.data[DOMAIN][entry_id]
    client = data["client"]
    try:
        return await asyncio.wait_for(factory(), timeout=COMMAND_TIMEOUT)
    except Exception as ex:  # noqa: BLE001 - timeout, or a stale/closed connection
        _LOGGER.debug("Command failed (%s); reconnecting and retrying", ex)
        async with data["lock"]:
            # Another task may have already reconnected while we waited.
            if not await async_is_alive(client):
                await _async_force_reconnect(client)
        return await asyncio.wait_for(factory(), timeout=COMMAND_TIMEOUT)
