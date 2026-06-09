"""Shared base for LG TV entities.

The shared ``WebOsClient`` is *replaced* (not mutated) when recovery reconnects
a wedged/zombie connection — see connection.py. Entities therefore must not
cache the client; they resolve it from ``hass.data`` on every access via the
``_client`` property below. Each entity sets ``self._entry`` in its own
``__init__`` (mirroring the existing pattern of not chaining ``Entity.__init__``).
"""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN


class LGTVEntity:
    _entry: ConfigEntry

    @property
    def _client(self):
        return self.hass.data[DOMAIN][self._entry.entry_id]["client"]

    @property
    def available(self) -> bool:
        return self._client.is_connected()

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.entry_id)})
