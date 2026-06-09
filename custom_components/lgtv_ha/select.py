from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .connection import READ_TIMEOUT, async_guarded_call
from .const import PICTURE_MODES
from .entity import LGTVEntity

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=10)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([LGTVPictureMode(entry), LGTVInput(entry)])


class LGTVPictureMode(LGTVEntity, SelectEntity):
    _attr_has_entity_name = True
    _attr_name = "Picture Mode"
    _attr_icon = "mdi:palette"
    _attr_options = PICTURE_MODES

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_picture_mode"
        self._picture_mode: str | None = None

    @property
    def current_option(self) -> str | None:
        return self._picture_mode

    async def async_update(self) -> None:
        if not self._client.is_connected():
            return
        try:
            settings = await asyncio.wait_for(
                self._client.get_picture_settings(["pictureMode"]),
                timeout=READ_TIMEOUT,
            )
            mode = settings.get("pictureMode")
            if mode is not None:
                self._picture_mode = mode
        except Exception as ex:  # noqa: BLE001
            _LOGGER.debug("Could not read pictureMode: %s", ex)

    async def async_select_option(self, option: str) -> None:
        # Writes go through the luna API (current input/mode context).
        await async_guarded_call(
            self.hass,
            self._entry.entry_id,
            lambda client: client.set_settings("picture", {"pictureMode": option}),
        )
        self._picture_mode = option
        self.async_write_ha_state()


class LGTVInput(LGTVEntity, SelectEntity):
    """Selects the active physical input (HDMI, etc.).

    The media_player's source list also includes inputs, but mixes in apps;
    this entity is just the TV's physical inputs for a clear, dedicated control.
    """

    _attr_has_entity_name = True
    _attr_name = "Input"
    _attr_icon = "mdi:hdmi-port"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_input"

    def _inputs(self) -> dict[str, str]:
        """Map of display label -> input id (e.g. {"PS5": "HDMI_2"})."""
        inputs: dict[str, str] = {}
        for inp in (self._client.inputs or {}).values():
            label = inp.get("label") or inp.get("id")
            if label and inp.get("id"):
                inputs[label] = inp["id"]
        return inputs

    @property
    def options(self) -> list[str]:
        return list(self._inputs().keys())

    @property
    def current_option(self) -> str | None:
        current = self._client.current_appId
        if not current:
            return None
        for inp in (self._client.inputs or {}).values():
            if inp.get("appId") == current:
                return inp.get("label") or inp.get("id")
        return None

    async def async_select_option(self, option: str) -> None:
        input_id = self._inputs().get(option)
        if input_id is None:
            _LOGGER.warning("Input '%s' not found in input list", option)
            return
        await async_guarded_call(
            self.hass,
            self._entry.entry_id,
            lambda client: client.set_input(input_id),
        )
