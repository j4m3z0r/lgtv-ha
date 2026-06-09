"""Standalone test for the LGTVEntity client-resolution mixin.

entity.py imports a couple of Home Assistant symbols, so we stub the minimal
``homeassistant.*`` modules in ``sys.modules`` before importing it (the approach
described in CLAUDE.md). The point being verified: entities resolve the shared
client from ``hass.data`` on every access and never cache it, so when recovery
swaps in a fresh client the entity immediately uses it.

Run: ``python3 tests/test_entity.py`` (exits non-zero on failure).
"""
from __future__ import annotations

import importlib.util
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
COMP = os.path.join(HERE, "..", "custom_components", "lgtv_ha")
PKG = "lgtv_ha_entity_under_test"


def _stub_homeassistant():
    ha = types.ModuleType("homeassistant")
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.ConfigEntry = object
    helpers = types.ModuleType("homeassistant.helpers")
    entity_mod = types.ModuleType("homeassistant.helpers.entity")

    class DeviceInfo(dict):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)

    entity_mod.DeviceInfo = DeviceInfo
    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.config_entries"] = config_entries
    sys.modules["homeassistant.helpers"] = helpers
    sys.modules["homeassistant.helpers.entity"] = entity_mod
    return DeviceInfo


def _load():
    DeviceInfo = _stub_homeassistant()
    pkg = types.ModuleType(PKG)
    pkg.__path__ = [os.path.abspath(COMP)]
    sys.modules[PKG] = pkg
    for name in ("const", "entity"):
        spec = importlib.util.spec_from_file_location(
            f"{PKG}.{name}", os.path.join(COMP, f"{name}.py")
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"{PKG}.{name}"] = mod
        spec.loader.exec_module(mod)
    return sys.modules[f"{PKG}.entity"], sys.modules[f"{PKG}.const"], DeviceInfo


entity, const, DeviceInfo = _load()
DOMAIN = const.DOMAIN


class FakeHass:
    def __init__(self):
        self.data = {}


class FakeEntry:
    entry_id = "e1"


class FakeClient:
    def __init__(self, connected):
        self._connected = connected

    def is_connected(self):
        return self._connected


class SampleEntity(entity.LGTVEntity):
    def __init__(self, hass, entry):
        self.hass = hass
        self._entry = entry


def test_resolves_current_client_not_cached():
    hass = FakeHass()
    entry = FakeEntry()
    c1 = FakeClient(connected=True)
    hass.data[DOMAIN] = {entry.entry_id: {"client": c1}}
    e = SampleEntity(hass, entry)

    assert e._client is c1
    assert e.available is True

    # Recovery swaps in a fresh client object; the entity must follow it.
    c2 = FakeClient(connected=False)
    hass.data[DOMAIN][entry.entry_id]["client"] = c2
    assert e._client is c2, "entity cached the old client instead of resolving it"
    assert e.available is False


def test_device_info_identifiers():
    hass = FakeHass()
    entry = FakeEntry()
    hass.data[DOMAIN] = {entry.entry_id: {"client": FakeClient(True)}}
    e = SampleEntity(hass, entry)
    info = e.device_info
    assert info["identifiers"] == {(DOMAIN, entry.entry_id)}, info


TESTS = [test_resolves_current_client_not_cached, test_device_info_identifiers]


def main():
    failures = 0
    for t in TESTS:
        try:
            t()
        except Exception as ex:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {t.__name__}: {type(ex).__name__}: {ex}")
        else:
            print(f"PASS  {t.__name__}")
    if failures:
        print(f"\n{failures} test(s) failed")
        sys.exit(1)
    print("\nall tests passed")


if __name__ == "__main__":
    main()
