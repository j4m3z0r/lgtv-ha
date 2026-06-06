# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Home Assistant **custom integration** (`custom_components/lgtv_ha/`, domain `lgtv_ha`) that controls an LG webOS TV over the LAN. It exposes a `media_player` (power/source/volume/playback/sound-output), four picture `number` sliders (OLED brightness/backlight, contrast, brightness, color — all driven by `PICTURE_NUMBERS` in `const.py`), two `select`s (picture mode + physical Input), two `button`s (screen on/off), and two services (`lgtv_ha.set_oled_light`, `lgtv_ha.send_message` for TV toasts). It talks to the TV via the `bscpylgtv` (`WebOsClient`) library.

There is no build, lint, or test tooling in this repo. "Running" it means deploying into a Home Assistant instance.

> **Library note:** this used to use `aiopylgtv`, which is abandoned and crashes on Python 3.12+ — it passes coroutines to `asyncio.wait()` (removed in 3.12) inside its connection-teardown, which corrupts the client so the TV never reconnects after a power-cycle. `bscpylgtv` is the maintained fork. **Do not re-introduce `register_state_update_callback`:** bscpylgtv has the *same* `asyncio.wait(closeout)` bug, and it only triggers when state-update callbacks are registered. This integration deliberately polls instead (see below). `aiowebostv` is not a drop-in — it has no picture-settings/calibration API.

## Deploy / test loop

There is no standalone entry point — the code only runs inside Home Assistant.

1. Copy `custom_components/lgtv_ha/` into a Home Assistant config's `custom_components/` directory.
2. **Restart Home Assistant** (a config-entry reload is *not* enough when `requirements` change — `bscpylgtv` is installed on startup; and the integration registry is only re-scanned at startup).
3. Add via **Settings → Devices & Services → + Add Integration → "LG TV"**, entering the TV's host. Accept the pairing prompt on the TV.

**Never place backups inside `custom_components/`.** A backup dir there (e.g. `lgtv_ha.bak-…`) carries a `manifest.json` with the same `domain`, which collides with the real integration and breaks loading (`Unable to import component …`). Keep backups elsewhere (e.g. `/config/lgtv_backups/`).

For HAOS over SSH, the live entity state / logs are reachable via the Supervisor's core API proxy: `curl -H "Authorization: Bearer $SUPERVISOR_TOKEN" http://supervisor/core/api/states/<entity>` (and `…/core/logs?lines=N`, `…/core/api/error_log`, `…/core/api/components`). `ha core logs` only returns a ~100-line tail.

## Architecture

Standard HA config-entry lifecycle, one shared `WebOsClient` per entry:

- `__init__.py` — `async_setup_entry` builds the client (in an executor — its `__init__` does blocking SSL setup), tries to connect (but does **not** fail setup if the TV is off — a TV is usually off), stores client + an `asyncio.Lock` under `hass.data[DOMAIN][entry_id]`, forwards the platforms, registers the `set_oled_light` service, and starts a background `_health_loop` (every 15s → `async_health_check`). Also backfills the TV's MAC (via `ip neigh`) for Wake-on-LAN.
- `connection.py` — connection health/recovery. `async_is_alive` probes with a timeout-bounded `get_power_state()`; `async_health_check` reconnects (disconnect→connect) when not alive; `async_guarded_call(hass, entry_id, factory)` runs a command and, on failure, forces one reconnect and retries once. A per-entry lock serializes reconnects. **All entity writes and the service go through `async_guarded_call`.**
- `config_flow.py` — single-step flow: connect (pairing prompt, generous `wait_for`), read `client.client_key`, store `{host, client_key, mac_address}`.
- `media_player.py` / `number.py` / `select.py` / `button.py` — the entities. `number.py` builds one `LGTVPictureNumber` per `PICTURE_NUMBERS` entry (generic 0-100 picture-key slider; **backlight keeps the legacy `_oled_brightness` unique_id** so the original entity isn't recreated). `select.py` has both Picture Mode and a physical-only `LGTVInput`. All **poll** (`SCAN_INTERVAL = 10s`); none register state-update callbacks. The connection stays open, so bscpylgtv's *internal* subscriptions keep the client's properties fresh between polls. **Every write (entities, buttons, both services) goes through `async_guarded_call`.**
- `key_storage.py` — `InMemoryKeyStorage`, a `StorageProto` stub so bscpylgtv doesn't persist the key to its own SQLite file (we use the config entry) and so first-time pairing's `storage.set_key(...)` doesn't `AttributeError`.
- `const.py` — `DOMAIN`, `PLATFORMS`, `CONF_*`, `PICTURE_MODES`, service/attr names.

### Key behaviors and gotchas

- **Polling, not push (intentional).** See the library note above — callbacks would re-introduce the crash. `available = client.is_connected()`; `media_player` reads live client properties; `number`/`select` fetch their value in `async_update`.
- **`is_connected()` lies — don't trust it for recovery.** After a power-cycle bscpylgtv can report `is_connected() == True` while the websocket is actually dead (a "zombie": `connect_task` still pending). Commands then fail with `ConnectionClosedOK: sent 1000 (OK); then received 1000 (OK)`, and a reconnect loop keyed on `is_connected()` never fires. Recovery therefore *probes* (`get_power_state` with a timeout) and force-reconnects via `connection.py` — both in the 15s health loop and on-demand in `async_guarded_call`. Never go back to an `if not is_connected(): connect()` reconnect.
- **Client key persists across restarts** via the config entry; the client is constructed with `client_key=…`, so a paired TV reconnects with no prompt.
- **Reads use ssap, writes use luna.** Reading picture settings uses `get_picture_settings(...)` (ssap `getSystemSettings`). Writing picture settings (OLED light, picture mode) **must** use `set_settings("picture", {...})` (the luna API) — the ssap `setSystemSettings` path is rejected for the picture category on at least some models (`"category, picture doesn't support the key(s): undefined"`). luna also targets the current input's context (settings are per-input).
- **Current picture mode often can't be read.** `get_picture_settings(["pictureMode"])` returns `"key not allowed"` on some webOS versions, so the `select` shows `unknown` until set. This is a TV limitation, not a regression (the original made the same call).
- **OLED light key is `backlight`.** `oledLight` is calibration-only and not subscribable.
- **MAC / Wake-on-LAN.** `async_turn_on` sends a WOL magic packet if a MAC is known; otherwise falls back to `client.power_on()`.
- **bscpylgtv specifics:** constructor is `WebOsClient(host, …)`; the calibration methods (`start_calibration`/`set_oled_light`/`set_contrast`) are gated behind `if np:` (need the numpy extra) and are deliberately unused here. `WebOsClient.__init__` does blocking SSL work — always build it in an executor.

### Verifying entity logic without a TV

`custom_components/lgtv_ha` can't be imported without Home Assistant, but the entity logic can be exercised by stubbing the `homeassistant.*` / `bscpylgtv` / `voluptuous` modules in `sys.modules` and driving the entities against a fake client — covering power-cycle recovery, key-based reconnect, `appId` source mapping, and the luna-based picture writes.
