from __future__ import annotations

import logging
import socket
from datetime import timedelta

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_MAC, DOMAIN

_LOGGER = logging.getLogger(__name__)

# Polled (not push): the persistent connection keeps the client's state fresh
# via bscpylgtv's internal subscriptions; HA re-reads it on this interval.
SCAN_INTERVAL = timedelta(seconds=10)

SUPPORTED_FEATURES = (
    MediaPlayerEntityFeature.TURN_ON
    | MediaPlayerEntityFeature.TURN_OFF
    | MediaPlayerEntityFeature.SELECT_SOURCE
    | MediaPlayerEntityFeature.VOLUME_SET
    | MediaPlayerEntityFeature.VOLUME_MUTE
    | MediaPlayerEntityFeature.VOLUME_STEP
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    client = hass.data[DOMAIN][entry.entry_id]["client"]
    async_add_entities([LGTVMediaPlayer(client, entry)])


class LGTVMediaPlayer(MediaPlayerEntity):
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = SUPPORTED_FEATURES

    def __init__(self, client, entry: ConfigEntry) -> None:
        self._client = client
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_media_player"

    @property
    def device_info(self) -> DeviceInfo:
        sys_info = self._client.system_info or {}
        sw_info = self._client.software_info or {}
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="LG",
            model=sys_info.get("modelName"),
            sw_version=sw_info.get("major_ver"),
        )

    @property
    def available(self) -> bool:
        return self._client.is_connected()

    @property
    def state(self) -> MediaPlayerState:
        if self._client.is_on:
            return MediaPlayerState.ON
        return MediaPlayerState.OFF

    @property
    def volume_level(self) -> float | None:
        vol = self._client.volume
        if vol is None:
            return None
        return vol / 100.0

    @property
    def is_volume_muted(self) -> bool | None:
        return self._client.muted

    @property
    def source_list(self) -> list[str]:
        inputs = self._client.inputs or {}
        return [
            inp.get("label") or inp.get("id", "")
            for inp in inputs.values()
            if inp.get("label") or inp.get("id")
        ]

    @property
    def source(self) -> str | None:
        inputs = self._client.inputs or {}
        current = self._client.current_appId
        for inp in inputs.values():
            if inp.get("appId") == current:
                return inp.get("label") or inp.get("id")
        return None

    @property
    def sound_mode(self) -> str | None:
        return self._client.sound_output

    async def async_turn_on(self) -> None:
        mac = self._entry.data.get(CONF_MAC)
        if mac:
            _send_wol(mac)
        else:
            await self._client.power_on()

    async def async_turn_off(self) -> None:
        await self._client.power_off()

    async def async_select_source(self, source: str) -> None:
        inputs = self._client.inputs or {}
        for inp in inputs.values():
            if inp.get("label") == source or inp.get("id") == source:
                await self._client.set_input(inp["id"])
                return
        _LOGGER.warning("Source '%s' not found in input list", source)

    async def async_set_volume_level(self, volume: float) -> None:
        await self._client.set_volume(int(volume * 100))

    async def async_mute_volume(self, mute: bool) -> None:
        await self._client.set_mute(mute)

    async def async_volume_up(self) -> None:
        await self._client.volume_up()

    async def async_volume_down(self) -> None:
        await self._client.volume_down()

    async def async_media_play(self) -> None:
        await self._client.play()

    async def async_media_pause(self) -> None:
        await self._client.pause()

    async def async_media_stop(self) -> None:
        await self._client.stop()


def _send_wol(mac: str) -> None:
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    magic = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(magic, ("<broadcast>", 9))
