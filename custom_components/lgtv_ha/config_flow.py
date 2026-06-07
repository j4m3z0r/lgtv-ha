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

    async def async_step_user(self, user_input=None):
        errors = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            try:
                from bscpylgtv import WebOsClient  # noqa: PLC0415

                # timeout_connect covers the WebSocket handshake only;
                # the outer wait_for gives the user time to accept the
                # pairing prompt on the TV remote.
                # Construct off the event loop (SSL context setup blocks).
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

                mac = _get_mac_address(host)

                unique_id = host.replace(".", "_").replace(":", "_")
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"LG TV ({host})",
                    data={CONF_HOST: host, CONF_CLIENT_KEY: client_key, CONF_MAC: mac},
                )

            except asyncio.TimeoutError:
                errors["base"] = "pairing_timeout"
            except Exception:
                _LOGGER.exception("Unexpected error connecting to %s", host)
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
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
