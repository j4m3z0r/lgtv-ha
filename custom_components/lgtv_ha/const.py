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
SERVICE_SEND_MESSAGE = "send_message"
ATTR_PICTURE_MODE = "picture_mode"
ATTR_VALUE = "value"
ATTR_MESSAGE = "message"

# Picture-setting sliders exposed as `number` entities. Each is a webOS
# "picture" key in the 0-100 range, read via ssap getSystemSettings and
# written via the luna set_settings("picture", ...) path (see CLAUDE.md).
# "backlight" is the OLED Light slider; "brightness" here is the black-level
# control, distinct from OLED Light.
PICTURE_NUMBERS = [
    # (webOS key, friendly name, icon)
    ("backlight", "OLED Brightness", "mdi:brightness-6"),
    ("contrast", "Contrast", "mdi:contrast-circle"),
    ("brightness", "Brightness", "mdi:brightness-5"),
    ("color", "Color", "mdi:palette-outline"),
]

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
