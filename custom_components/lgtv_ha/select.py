from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, PICTURE_MODES

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=10)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    async_add_entities([LGTVPictureMode(client, entry)])


class LGTVPictureMode(SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Picture Mode"
    _attr_icon = "mdi:palette"
    _attr_options = PICTURE_MODES

    def __init__(self, client, entry: ConfigEntry) -> None:
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_picture_mode"
        self._picture_mode: str | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.entry_id)})

    @property
    def available(self) -> bool:
        return self._client.is_connected()

    @property
    def current_option(self) -> str | None:
        return self._picture_mode

    async def async_update(self) -> None:
        if not self._client.is_connected():
            return
        try:
            settings = await self._client.get_picture_settings(["pictureMode"])
            mode = settings.get("pictureMode")
            if mode is not None:
                self._picture_mode = mode
        except Exception as ex:  # noqa: BLE001
            _LOGGER.debug("Could not read pictureMode: %s", ex)

    async def async_select_option(self, option: str) -> None:
        # Writes go through the luna API (current input/mode context).
        await self._client.set_settings("picture", {"pictureMode": option})
        self._picture_mode = option
        self.async_write_ha_state()
