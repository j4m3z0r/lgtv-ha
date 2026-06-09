from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .connection import async_guarded_call
from .entity import LGTVEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities(
        [
            LGTVScreenButton(entry, on=False),
            LGTVScreenButton(entry, on=True),
        ]
    )


class LGTVScreenButton(LGTVEntity, ButtonEntity):
    """Turns the OLED panel off (audio keeps playing) or back on."""

    _attr_has_entity_name = True

    def __init__(self, entry: ConfigEntry, *, on: bool) -> None:
        self._entry = entry
        self._on = on
        suffix = "screen_on" if on else "screen_off"
        self._attr_name = "Screen On" if on else "Screen Off"
        self._attr_icon = "mdi:television-shimmer" if on else "mdi:television-off"
        self._attr_unique_id = f"{entry.entry_id}_{suffix}"

    async def async_press(self) -> None:
        on = self._on
        await async_guarded_call(
            self.hass,
            self._entry.entry_id,
            lambda client: (client.turn_screen_on if on else client.turn_screen_off)(),
        )
