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
from homeassistant.exceptions import ConfigEntryNotReady
import homeassistant.helpers.config_validation as cv

from .const import (
    ATTR_PICTURE_MODE,
    ATTR_VALUE,
    CONF_CLIENT_KEY,
    CONF_MAC,
    DOMAIN,
    PLATFORMS,
    SERVICE_SET_OLED_LIGHT,
)
from .key_storage import InMemoryKeyStorage

_LOGGER = logging.getLogger(__name__)

# Only attempt the websocket connect once so an unreachable (powered-off) TV
# fails fast instead of blocking inside bscpylgtv's retry loop.
CONNECT_RETRY_ATTEMPTS = 1

SET_OLED_LIGHT_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_PICTURE_MODE): cv.string,
        vol.Required(ATTR_VALUE): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
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

    try:
        await asyncio.wait_for(client.connect(), timeout=15)
    except Exception as ex:
        _LOGGER.warning("Cannot connect to LG TV at %s: %s", host, ex)
        raise ConfigEntryNotReady(f"Cannot connect to LG TV at {host}") from ex

    # Backfill MAC address if missing from an older config entry
    if not entry.data.get(CONF_MAC):
        mac = _get_mac_address(host)
        if mac:
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_MAC: mac}
            )

    hass.data[DOMAIN][entry.entry_id] = {"client": client}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _async_register_services(hass)

    entry.async_create_background_task(
        hass,
        _reconnect_loop(hass, entry),
        "lgtv_ha_reconnect",
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        client = hass.data[DOMAIN].pop(entry.entry_id)["client"]
        await client.disconnect()
    return unload_ok


async def _reconnect_loop(hass: HomeAssistant, entry: ConfigEntry) -> None:
    while True:
        await asyncio.sleep(30)
        data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if data is None:
            return
        client = data["client"]
        if not client.is_connected():
            try:
                await asyncio.wait_for(client.connect(), timeout=15)
                _LOGGER.info("Reconnected to LG TV at %s", entry.data[CONF_HOST])
            except Exception as ex:
                _LOGGER.debug("Reconnect attempt failed: %s", ex)


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
        for data in hass.data.get(DOMAIN, {}).values():
            client = data["client"]
            if not client.is_connected():
                continue
            # Switch picture mode first (if requested) so the OLED light value
            # is applied to that mode. "backlight" is the webOS OLED-light key.
            # Writes use the luna API (set_settings), per the picture-category
            # limitation of the ssap setSystemSettings endpoint on this TV.
            if pic_mode:
                await client.set_settings("picture", {"pictureMode": pic_mode})
            await client.set_settings("picture", {"backlight": value})

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_OLED_LIGHT,
        handle_set_oled_light,
        schema=SET_OLED_LIGHT_SCHEMA,
    )
