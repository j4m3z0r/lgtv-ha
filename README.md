# LG TV Control for Home Assistant

A custom integration (`lgtv_ha`) to control an LG webOS TV from Home Assistant
over the local network.

## Features

- **Media player**
  - Power on (Wake-on-LAN) / off.
  - Source selection across both physical inputs (HDMI, AV) **and** installed
    apps (Netflix, YouTube, Disney+, …).
  - Volume set / mute / up / down.
  - Play / pause / stop.
  - Sound output selection (sound mode): TV speaker, HDMI-ARC, optical,
    Bluetooth, etc.
- **Picture sliders** (`number`) — read and set, for the current input:
  - **OLED Brightness** (OLED light / backlight)
  - **Contrast**
  - **Brightness** (black level)
  - **Color** (saturation)
- **Input** (`select`) — switch directly between the TV's physical inputs
  (HDMI 1–4, AV, …). The media player's source list also offers these, mixed in
  with apps; this entity is a clean inputs-only control.
- **Picture Mode** (`select`) — set the picture mode.
- **Screen On / Screen Off** (`button`) — turn the OLED panel off while audio
  keeps playing, and back on.
- **`lgtv_ha.set_oled_light` service** — set the OLED light level, optionally
  for a specific picture mode.
- **`lgtv_ha.send_message` service** — show a floating toast message on the TV.

## Requirements

- Home Assistant running on Python 3.12 or newer.
- The integration depends on [`bscpylgtv`](https://pypi.org/project/bscpylgtv/),
  which Home Assistant installs automatically.

## Installation

1. Copy `custom_components/lgtv_ha/` into your Home Assistant `custom_components`
   directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → + Add Integration**, search for
   **"LG TV"**, and enter the TV's hostname or IP.
4. Accept the pairing prompt that appears on the TV. The resulting client key is
   stored in the config entry, so you only pair once — it survives restarts.

## Notes & limitations

- **Polling.** State is refreshed about every 10 seconds (the connection is held
  open, so remote-initiated changes appear within that window). The integration
  reconnects automatically after the TV is powered off and back on — no Home
  Assistant restart needed.
- **Wake-on-LAN.** Turn-on sends a WOL magic packet to the TV's MAC address,
  which is auto-detected via ARP at setup. "Turn on the TV from the TV's network"
  must be enabled on the TV for this to work.
- **Reading the current picture mode** is rejected by some webOS versions
  (the TV returns "key not allowed"); in that case the Picture Mode entity shows
  `unknown` until you set it. Setting the picture mode always works.
- **Writes use the TV's luna API.** Picture settings (OLED light, picture mode)
  are written via `set_settings`, which targets the current input's context — the
  plain `setSystemSettings` request is rejected for the picture category on at
  least some models.

## History

This integration originally used `aiopylgtv`, which is unmaintained and crashes
on Python 3.12+ (it passes coroutines to `asyncio.wait()`, removed in 3.12),
leaving the TV stuck "unavailable" after a power cycle. It now uses the
maintained `bscpylgtv` fork and a polling model that avoids the crash.
