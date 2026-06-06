# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Home Assistant **custom integration** (`custom_components/lgtv/`) that exposes an LG webOS TV as a `media_player` entity. It can select the HDMI/input source and set picture-calibration settings (picture mode, contrast, OLED brightness). It is `local_polling` and talks to the TV over the LAN via the `aiopylgtv` (`WebOsClient`) library.

There is no build, lint, or test tooling in this repo. "Running" it means deploying into a Home Assistant instance.

## Deploy / test loop

There is no standalone entry point — the code only runs inside Home Assistant.

1. Copy `custom_components/lgtv/` into a Home Assistant config's `custom_components/` directory.
2. Restart Home Assistant.
3. Add via **Settings > Devices & Services > + Add Integration > "LG TV Control"**, entering the TV's IP.
4. The config flow calls `client.connect()`, which triggers the on-TV pairing prompt; the resulting `client_key` is persisted in the config entry.

`manifest.json` declares `requirements: ["aiopylgtv"]` — Home Assistant installs this automatically. Bump `version` in `manifest.json` when releasing.

## Architecture

The integration follows the standard HA config-entry lifecycle:

- `__init__.py` — `async_setup_entry` / `async_unload_entry`. Stores per-entry state under `hass.data[DOMAIN][entry_id]["entities"]` and forwards setup to the platforms listed in `const.py` (`PLATFORMS = ["media_player"]`).
- `config_flow.py` — single-step user flow. Sets `unique_id` to the TV's IP (`_abort_if_unique_id_configured` prevents duplicates), pairs with a 30s timeout, and stores `{ip_address, client_key}` in the entry data.
- `media_player.py` — `LGTVMediaPlayer` entity plus registration of the `lgtv.set_picture_settings` service. Each `WebOsClient` call uses a **connect → act → disconnect** pattern within every method (`async_update`, `async_select_source`, `async_set_picture_settings`); the client is not kept connected between polls.
- `services.yaml` — UI/selector metadata for `set_picture_settings`. The runtime validation schema is `SET_PICTURE_SETTINGS_SCHEMA` in `media_player.py` (voluptuous); keep the two in sync when changing fields.
- `const.py` — `DOMAIN = "lgtv"` and `PLATFORMS`.

### Key behaviors and gotchas

- **Picture calibration is bracketed**: `set_picture_settings` calls `start_calibration(picMode=...)`, applies `set_contrast` / `set_oled_light`, then `end_calibration` in a `finally`. Preserve this start/end pairing — changes only take effect inside an open calibration session.
- **`supported_features` is only `SELECT_SOURCE`** — this is a control/calibration entity, not a full media player (no play/pause/volume). Add the corresponding `MediaPlayerEntityFeature` flag if you implement new controls.
- **Source list comes from the TV at poll time**: `async_update` fetches `get_inputs()` into `self._inputs`; sources are matched by the `label` field, and `select_source` maps label → `id`. The list is empty until a successful poll.
- **Errors are swallowed**: the entity-level methods catch broad `Exception` and just set `self._available = False` / `state = "off"`. When debugging connectivity, this will mask the real error — add logging or re-raise locally.
- **Identifier inconsistency to be aware of when touching IDs**: config-flow `unique_id` and `device_info` identifiers use the IP, but the entity's `unique_id` property is `f"lgtv_{self._client.host}"`. Changing any of these affects entity/device identity in existing installs.
