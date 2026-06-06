from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    async_add_entities(
        [
            LGTVScreenButton(client, entry, on=False),
            LGTVScreenButton(client, entry, on=True),
        ]
    )


class LGTVScreenButton(ButtonEntity):
    """Turns the OLED panel off (audio keeps playing) or back on."""

    _attr_has_entity_name = True

    def __init__(self, client, entry: ConfigEntry, *, on: bool) -> None:
        self._client = client
        self._entry = entry
        self._on = on
        suffix = "screen_on" if on else "screen_off"
        self._attr_name = "Screen On" if on else "Screen Off"
        self._attr_icon = "mdi:television-shimmer" if on else "mdi:television-off"
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.entry_id)})

    @property
    def available(self) -> bool:
        return self._client.is_connected()

    async def async_press(self) -> None:
        if self._on:
            await self._client.turn_screen_on()
        else:
            await self._client.turn_screen_off()
