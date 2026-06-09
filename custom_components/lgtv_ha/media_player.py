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

from .connection import async_guarded_call
from .const import CONF_MAC, DOMAIN, SOUND_OUTPUTS
from .entity import LGTVEntity

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
    | MediaPlayerEntityFeature.SELECT_SOUND_MODE
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([LGTVMediaPlayer(entry)])


class LGTVMediaPlayer(LGTVEntity, MediaPlayerEntity):
    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_has_entity_name = True
    _attr_name = None
    _attr_supported_features = SUPPORTED_FEATURES

    def __init__(self, entry: ConfigEntry) -> None:
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

    def _sources(self) -> dict[str, dict]:
        """Map of selectable source name -> action descriptor.

        Combines physical inputs (HDMI etc.) with launchable apps (Netflix,
        YouTube, ...). Inputs win over the app launch-points that represent the
        same thing (e.g. the HDMI apps), so each input appears once.
        """
        inputs = self._client.inputs or {}
        apps = self._client.apps or {}
        sources: dict[str, dict] = {}
        input_app_ids = set()
        for inp in inputs.values():
            name = inp.get("label") or inp.get("id")
            if name:
                sources[name] = {"kind": "input", "id": inp["id"]}
                if inp.get("appId"):
                    input_app_ids.add(inp["appId"])
        for app in apps.values():
            app_id = app.get("id")
            title = app.get("title")
            if title and app_id and app_id not in input_app_ids:
                sources.setdefault(title, {"kind": "app", "id": app_id, "app_id": app_id})
        return sources

    @property
    def source_list(self) -> list[str]:
        return list(self._sources().keys())

    @property
    def source(self) -> str | None:
        current = self._client.current_appId
        if not current:
            return None
        inputs = self._client.inputs or {}
        for inp in inputs.values():
            if inp.get("appId") == current:
                return inp.get("label") or inp.get("id")
        app = (self._client.apps or {}).get(current)
        if app:
            return app.get("title")
        return None

    @property
    def sound_mode(self) -> str | None:
        return self._client.sound_output

    @property
    def sound_mode_list(self) -> list[str]:
        # Include the current output even if it's not in our static list.
        current = self._client.sound_output
        if current and current not in SOUND_OUTPUTS:
            return [current, *SOUND_OUTPUTS]
        return SOUND_OUTPUTS

    async def _call(self, factory):
        """Run a client command, reconnecting and retrying once on failure."""
        return await async_guarded_call(self.hass, self._entry.entry_id, factory)

    async def async_turn_on(self) -> None:
        mac = self._entry.data.get(CONF_MAC)
        if mac:
            _send_wol(mac)
        else:
            await self._call(lambda client: client.power_on())

    async def async_turn_off(self) -> None:
        await self._call(lambda client: client.power_off())

    async def async_select_source(self, source: str) -> None:
        target = self._sources().get(source)
        if target is None:
            _LOGGER.warning("Source '%s' not found in source list", source)
            return
        if target["kind"] == "input":
            await self._call(lambda client: client.set_input(target["id"]))
        else:
            await self._call(lambda client: client.launch_app(target["app_id"]))

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        await self._call(lambda client: client.change_sound_output(sound_mode))

    async def async_set_volume_level(self, volume: float) -> None:
        await self._call(lambda client: client.set_volume(int(volume * 100)))

    async def async_mute_volume(self, mute: bool) -> None:
        await self._call(lambda client: client.set_mute(mute))

    async def async_volume_up(self) -> None:
        await self._call(lambda client: client.volume_up())

    async def async_volume_down(self) -> None:
        await self._call(lambda client: client.volume_down())

    async def async_media_play(self) -> None:
        await self._call(lambda client: client.play())

    async def async_media_pause(self) -> None:
        await self._call(lambda client: client.pause())

    async def async_media_stop(self) -> None:
        await self._call(lambda client: client.stop())


def _send_wol(mac: str) -> None:
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    magic = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(magic, ("<broadcast>", 9))
