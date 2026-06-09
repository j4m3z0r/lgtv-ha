"""Connection health/recovery helpers for the shared WebOsClient.

bscpylgtv's ``is_connected()`` only checks whether the internal connect task is
still pending — after the TV is powered off it can report ``True`` while the
underlying websocket is already dead (a "zombie" connection). Relying on it
alone means the background reconnect never fires and every command fails with
``ConnectionClosedOK``. These helpers instead probe the connection with a real,
timeout-bounded request and force a clean reconnect when it isn't actually alive.

**Recovery never awaits a zombie's ``disconnect()``.** bscpylgtv's connection
teardown re-shields its closeout task and *swallows* ``CancelledError`` until a
``ws.close()`` handshake that a dead socket never completes — so ``disconnect()``
is effectively uncancellable and ``asyncio.wait_for(disconnect(), timeout=...)``
hangs forever instead of timing out. If recovery awaited it under the per-entry
lock, that lock would be held forever: every write would block on it (the slider
"does nothing", returning a gateway timeout) and the health loop would wedge too.
Instead we *abandon* the wedged client (best-effort cancel of its connect task,
no await) and build a brand-new client, swapping it into ``hass.data`` so callers
and entities pick it up. The orphaned client only mutates its own (now
unreferenced) state when its closeout eventually finishes, so it can't clobber
the fresh connection.
"""
from __future__ import annotations

import asyncio
import logging

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PROBE_TIMEOUT = 5
RECONNECT_TIMEOUT = 15
# Every request to the TV must be bounded. bscpylgtv has no per-request
# timeout, so a request issued on a zombie socket (writable but dead) blocks
# forever instead of raising. Unbounded, that freezes entity polls, hangs the
# service call behind a slider/command, and — because the hang never raises —
# stops async_guarded_call from ever reaching its reconnect path, so the
# connection never self-heals. Bounding turns all of that into a fast,
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


def release_client(client) -> None:
    """Abandon a (possibly zombie) client without awaiting its teardown.

    We never ``await client.disconnect()``: on a dead socket that call is
    uncancellable and would hang forever (see module docstring). Cancelling the
    connect task is best-effort — bscpylgtv may swallow the cancellation, but its
    closeout only touches its own object, which we are about to stop referencing.
    """
    if client is None:
        return
    task = getattr(client, "connect_task", None)
    if task is not None and not task.done():
        task.cancel()


async def _async_force_reconnect(hass, entry_id) -> bool:
    """Abandon the current client and connect a fresh one in its place.

    Callers must hold the per-entry lock. The new client is stored in
    ``hass.data`` even if the connect fails, so the next attempt starts from a
    clean object instead of reusing the wedged one.
    """
    data = hass.data[DOMAIN].get(entry_id)
    if data is None:
        return False
    release_client(data.get("client"))
    client = await data["make_client"]()
    data["client"] = client
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
    async with data["lock"]:
        if await async_is_alive(data["client"]):
            return True
        _LOGGER.debug("Connection not alive; forcing reconnect")
        return await _async_force_reconnect(hass, entry_id)


async def async_guarded_call(hass, entry_id, factory):
    """Run ``factory(client)``; on failure, force one reconnect and retry once.

    ``factory`` takes the *current* client and returns the awaitable to run, so
    the retry runs against the freshly reconnected client rather than the wedged
    one it failed on. Each attempt is bounded by ``COMMAND_TIMEOUT``: a request
    on a zombie socket would otherwise hang forever, so the timeout is what lets
    a stuck command both fail fast *and* drive the reconnect below.
    """
    data = hass.data[DOMAIN][entry_id]
    try:
        return await asyncio.wait_for(factory(data["client"]), timeout=COMMAND_TIMEOUT)
    except Exception as ex:  # noqa: BLE001 - timeout, or a stale/closed connection
        _LOGGER.debug("Command failed (%s); reconnecting and retrying", ex)
        async with data["lock"]:
            # Another task may have already reconnected while we waited.
            if not await async_is_alive(data["client"]):
                await _async_force_reconnect(hass, entry_id)
        return await asyncio.wait_for(factory(data["client"]), timeout=COMMAND_TIMEOUT)
