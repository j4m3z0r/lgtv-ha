from __future__ import annotations

import asyncio
import logging
from functools import partial

import voluptuous as vol
import re
import subprocess

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import (
    ATTR_MESSAGE,
    ATTR_PICTURE_MODE,
    ATTR_VALUE,
    CONF_CLIENT_KEY,
    CONF_MAC,
    DOMAIN,
    PLATFORMS,
    SERVICE_SEND_MESSAGE,
    SERVICE_SET_OLED_LIGHT,
)
from .connection import async_guarded_call, async_health_check
from .key_storage import InMemoryKeyStorage

_LOGGER = logging.getLogger(__name__)

# How often to probe the connection and reconnect if it's down or zombie.
HEALTH_CHECK_INTERVAL = 15

# Only attempt the websocket connect once so an unreachable (powered-off) TV
# fails fast instead of blocking inside bscpylgtv's retry loop.
CONNECT_RETRY_ATTEMPTS = 1

SET_OLED_LIGHT_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_PICTURE_MODE): cv.string,
        vol.Required(ATTR_VALUE): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
    }
)

SEND_MESSAGE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_MESSAGE): cv.string,
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from bscpylgtv import WebOsClient  # noqa: PLC0415

    hass.data.setdefault(DOMAIN, {})

    host = entry.data[CONF_HOST]
    client_key = entry.data.get(CONF_CLIENT_KEY)
    # The key is loaded from the (persisted) config entry, so a paired TV
    # reconnects on restart without prompting to pair again.
    # Construct off the event loop: WebOsClient builds an SSL context in its
    # __init__, which does blocking file I/O (loading CA certificates).
    client = await hass.async_add_executor_job(
        partial(
            WebOsClient,
            host,
            client_key=client_key,
            storage=InMemoryKeyStorage(client_key),
            timeout_connect=10,
            connect_retry_attempts=CONNECT_RETRY_ATTEMPTS,
        )
    )

    # A TV is off most of the time, so don't fail setup when it's unreachable:
    # set up anyway (entities show unavailable) and let the health loop connect
    # once the TV turns on. This also recovers from power-cycles within ~15s.
    try:
        await asyncio.wait_for(client.connect(), timeout=15)
    except Exception as ex:  # noqa: BLE001
        _LOGGER.info(
            "LG TV at %s not reachable at setup; will connect when it turns on (%s)",
            host,
            ex,
        )

    # Backfill MAC address if missing from an older config entry
    if not entry.data.get(CONF_MAC):
        mac = _get_mac_address(host)
        if mac:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_MAC: mac}
            )

    # The lock serializes reconnects across the entities and the health loop.
    hass.data[DOMAIN][entry.entry_id] = {"client": client, "lock": asyncio.Lock()}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)

    entry.async_create_background_task(
        hass,
        _health_loop(hass, entry),
        "lgtv_ha_health",
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        client = hass.data[DOMAIN].pop(entry.entry_id)["client"]
        await client.disconnect()
    return unload_ok


async def _health_loop(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Periodically probe the connection and reconnect if it's down or zombie."""
    while True:
        await asyncio.sleep(HEALTH_CHECK_INTERVAL)
        if hass.data.get(DOMAIN, {}).get(entry.entry_id) is None:
            return
        await async_health_check(hass, entry.entry_id)


def _get_mac_address(host: str) -> str | None:
    try:
        result = subprocess.run(
            ["ip", "neigh", "show", host],
            capture_output=True, text=True, timeout=5,
        )
        match = re.search(
            r"lladdr\s+((?:[0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2})",
            result.stdout,
        )
        return match.group(1) if match else None
    except Exception:
        return None


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_OLED_LIGHT):
        return

    async def handle_set_oled_light(call: ServiceCall) -> None:
        value = call.data[ATTR_VALUE]
        pic_mode = call.data.get(ATTR_PICTURE_MODE)
        for entry_id, data in hass.data.get(DOMAIN, {}).items():
            client = data["client"]

            async def _apply(client=client):
                # Switch picture mode first (if requested) so the OLED light
                # value applies to that mode. "backlight" is the webOS
                # OLED-light key. Writes use the luna API (set_settings), per
                # the ssap setSystemSettings picture-category limitation.
                if pic_mode:
                    await client.set_settings("picture", {"pictureMode": pic_mode})
                await client.set_settings("picture", {"backlight": value})

            try:
                await async_guarded_call(hass, entry_id, _apply)
            except Exception as ex:  # noqa: BLE001
                _LOGGER.warning("set_oled_light failed for %s: %s", entry_id, ex)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_OLED_LIGHT,
        handle_set_oled_light,
        schema=SET_OLED_LIGHT_SCHEMA,
    )

    async def handle_send_message(call: ServiceCall) -> None:
        message = call.data[ATTR_MESSAGE]
        for entry_id, data in hass.data.get(DOMAIN, {}).items():
            client = data["client"]
            try:
                await async_guarded_call(
                    hass, entry_id, lambda client=client: client.send_message(message)
                )
            except Exception as ex:  # noqa: BLE001
                _LOGGER.warning("send_message failed for %s: %s", entry_id, ex)

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_MESSAGE,
        handle_send_message,
        schema=SEND_MESSAGE_SCHEMA,
    )
