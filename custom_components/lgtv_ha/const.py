DOMAIN = "lgtv_ha"
PLATFORMS = ["media_player", "number", "select", "button"]

CONF_CLIENT_KEY = "client_key"
CONF_MAC = "mac_address"

PICTURE_MODES = [
    "cinema",
    "eco",
    "expert1",
    "expert2",
    "game",
    "normal",
    "photo",
    "sports",
    "vivid",
]
DEFAULT_PICTURE_MODE = "expert1"

SERVICE_SET_OLED_LIGHT = "set_oled_light"
ATTR_PICTURE_MODE = "picture_mode"
ATTR_VALUE = "value"

# Common webOS sound outputs offered by the sound_mode select. The TV may not
# support every one; selecting an unsupported value is simply rejected.
SOUND_OUTPUTS = [
    "tv_speaker",
    "external_optical",
    "external_arc",
    "external_speaker",
    "lineout",
    "headphone",
    "bt_soundbar",
]
