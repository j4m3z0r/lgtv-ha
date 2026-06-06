
from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
)
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN
from aiopylgtv import WebOsClient
import voluptuous as vol

SERVICE_SET_PICTURE_SETTINGS = "set_picture_settings"

SET_PICTURE_SETTINGS_SCHEMA = vol.Schema(
    {
        vol.Optional("picture_mode"): str,
        vol.Optional("contrast"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional("oled_brightness"): vol.All(
            vol.Coerce(int), vol.Range(min=0, max=100)
        ),
    }
)


async def async_setup_entry(hass, config_entry, async_add_entities):
    client = WebOsClient(config_entry.data["ip_address"], client_key=config_entry.data.get("client_key"))
    device_info = {
        "identifiers": {(DOMAIN, config_entry.unique_id)},
        "name": client.host,
        "manufacturer": "LG",
    }
    entity = LGTVMediaPlayer(client, device_info, config_entry.entry_id)
    hass.data[DOMAIN][config_entry.entry_id]["entities"].append(entity)
    async_add_entities([entity])

    async def async_set_picture_settings(call):
        entity_ids = call.data.get("entity_id")
        entities = hass.data[DOMAIN][config_entry.entry_id]["entities"]
        for entity in entities:
            if entity.entity_id in entity_ids:
                await entity.async_set_picture_settings(
                    call.data.get("picture_mode"),
                    call.data.get("contrast"),
                    call.data.get("oled_brightness"),
                )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_PICTURE_SETTINGS,
        async_set_picture_settings,
        schema=SET_PICTURE_SETTINGS_SCHEMA,
    )


class LGTVMediaPlayer(MediaPlayerEntity):
    def __init__(self, client, device_info, entry_id):
        self._client = client
        self._device_info = device_info
        self._name = f"LG TV ({self._client.host})"
        self._state = "off"
        self._source = None
        self._source_list = []
        self._inputs = []
        self._available = False

    @property
    def device_info(self) -> DeviceInfo:
        return self._device_info

    @property
    def name(self):
        return self._name

    @property
    def unique_id(self):
        return f"lgtv_{self._client.host}"

    @property
    def available(self):
        return self._available

    @property
    def state(self):
        return self._state

    @property
    def supported_features(self):
        return MediaPlayerEntityFeature.SELECT_SOURCE

    @property
    def source_list(self):
        return self._source_list

    @property
    def source(self):
        return self._source

    async def async_update(self):
        try:
            await self._client.connect()
            self._available = self._client.is_connected()
            if self._available:
                self._inputs = await self._client.get_inputs()
                self._source_list = [inp["label"] for inp in self._inputs]
                current_input_id = await self._client.get_current_input()
                self._source = next(
                    (inp["label"] for inp in self._inputs if inp["id"] == current_input_id),
                    None,
                )
                self._state = "on"
        except Exception:
            self._available = False
            self._state = "off"
        finally:
            await self._client.disconnect()

    async def async_select_source(self, source: str):
        try:
            await self._client.connect()
            input_dict = next(
                (inp for inp in self._inputs if inp["label"] == source), None
            )
            if input_dict:
                await self._client.set_input(input_dict["id"])
                self._source = source
        except Exception:
            self._available = False
        finally:
            await self._client.disconnect()
        self.async_write_ha_state()

    async def async_set_picture_settings(self, picture_mode, contrast, oled_brightness):
        try:
            await self._client.connect()
            if picture_mode:
                await self._client.start_calibration(picMode=picture_mode)
            else:
                # If no picture_mode is provided, try to get the current one
                picture_mode = await self._client.get_current_picture_mode()
                if picture_mode:
                    await self._client.start_calibration(picMode=picture_mode)

            if contrast is not None:
                await self._client.set_contrast(picMode=picture_mode, value=contrast)
            if oled_brightness is not None:
                await self._client.set_oled_light(picMode=picture_mode, value=oled_brightness)

        except Exception:
            self._available = False
        finally:
            if picture_mode:
                await self._client.end_calibration(picMode=picture_mode)
            await self._client.disconnect()
        self.async_write_ha_state()
