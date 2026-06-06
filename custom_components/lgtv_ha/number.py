from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .connection import async_guarded_call
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=10)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    async_add_entities([LGTVOledBrightness(client, entry)])


class LGTVOledBrightness(NumberEntity):
    _attr_has_entity_name = True
    _attr_name = "OLED Brightness"
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:brightness-6"

    def __init__(self, client, entry: ConfigEntry) -> None:
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_oled_brightness"
        self._oled_light: int | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(identifiers={(DOMAIN, self._entry.entry_id)})

    @property
    def available(self) -> bool:
        return self._client.is_connected()

    @property
    def native_value(self) -> float | None:
        return self._oled_light

    async def async_update(self) -> None:
        # "backlight" is the webOS key for the OLED Light slider.
        if not self._client.is_connected():
            return
        try:
            settings = await self._client.get_picture_settings(["backlight"])
            val = settings.get("backlight")
            if val is not None:
                self._oled_light = int(val)
        except Exception as ex:  # noqa: BLE001
            _LOGGER.debug("Could not read backlight: %s", ex)

    async def async_set_native_value(self, value: float) -> None:
        int_value = int(value)
        # Writes go through the luna API (set_settings), which targets the
        # current input/mode context. The ssap setSystemSettings endpoint
        # rejects picture-category writes on this TV ("undefined" key error).
        await async_guarded_call(
            self.hass,
            self._entry.entry_id,
            lambda: self._client.set_settings("picture", {"backlight": int_value}),
        )
        self._oled_light = int_value
        self.async_write_ha_state()
