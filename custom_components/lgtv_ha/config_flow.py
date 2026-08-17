from __future__ import annotations

import asyncio
import logging
import re
import socket
import subprocess
from functools import partial

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST

from .const import CONF_CLIENT_KEY, CONF_MAC, DOMAIN
from .key_storage import InMemoryKeyStorage

_LOGGER = logging.getLogger(__name__)


class LGTVConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def _async_pair(self, host: str) -> str:
        """Connect to the TV and return a freshly paired client key.

        An empty key storage forces bscpylgtv to do a fresh registration, so the
        TV shows a pairing prompt the user accepts on the remote. ``timeout_connect``
        covers only the WebSocket handshake; the outer ``wait_for`` gives the user
        time to accept the prompt (raises ``asyncio.TimeoutError`` if they don't).
        Construct the client off the event loop — its ``__init__`` does blocking
        SSL setup.
        """
        from bscpylgtv import WebOsClient  # noqa: PLC0415

        client = await self.hass.async_add_executor_job(
            partial(
                WebOsClient,
                host,
                storage=InMemoryKeyStorage(),
                timeout_connect=10,
                connect_retry_attempts=1,
            )
        )
        await asyncio.wait_for(client.connect(), timeout=60)
        client_key = client.client_key
        await client.disconnect()
        return client_key

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                client_key = await self._async_pair(host)
            except asyncio.TimeoutError:
                errors["base"] = "pairing_timeout"
            except Exception:
                _LOGGER.exception("Unexpected error connecting to %s", host)
                errors["base"] = "cannot_connect"
            else:
                mac = _get_mac_address(host)

                unique_id = host.replace(".", "_").replace(":", "_")
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"LG TV ({host})",
                    data={CONF_HOST: host, CONF_CLIENT_KEY: client_key, CONF_MAC: mac},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input=None):
        """Re-pair an existing entry in place.

        A TV factory reset invalidates the stored client key, after which the TV
        rejects it (401) and every entity goes unavailable. This flow re-pairs and
        writes a fresh key into the *same* config entry — no delete/re-add — then
        reloads it. Triggered from the integration's "Reconfigure" menu item.
        """
        errors = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                client_key = await self._async_pair(host)
            except asyncio.TimeoutError:
                errors["base"] = "pairing_timeout"
            except Exception:
                _LOGGER.exception("Unexpected error re-pairing with %s", host)
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_HOST: host,
                        CONF_CLIENT_KEY: client_key,
                        CONF_MAC: _get_mac_address(host),
                    },
                )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {vol.Required(CONF_HOST, default=entry.data.get(CONF_HOST, "")): str}
            ),
            errors=errors,
        )


def _get_mac_address(host: str) -> str | None:
    """Return the MAC address for host via ARP, or None if not found.

    ``ip neigh show`` filters by IP, not hostname, so resolve to the IP first;
    otherwise it lists every neighbour and we'd match an arbitrary device.
    """
    try:
        ip = socket.gethostbyname(host)
        result = subprocess.run(
            ["ip", "neigh", "show", ip],
            capture_output=True, text=True, timeout=5,
        )
        match = re.search(
            r"lladdr\s+((?:[0-9a-fA-F]{2}[:\-]){5}[0-9a-fA-F]{2})",
            result.stdout,
        )
        return match.group(1) if match else None
    except Exception:
        return None
