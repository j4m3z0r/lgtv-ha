"""Minimal in-memory client-key storage for bscpylgtv.

bscpylgtv's ``WebOsClient`` otherwise persists the paired client key to a SQLite
file. We manage the key via the Home Assistant config entry instead, so this
in-memory implementation satisfies bscpylgtv's storage interface without
touching the filesystem.

It is also required during first-time pairing: ``connect_handler`` calls
``storage.set_key(...)`` when the TV returns a freshly paired key, which would
raise ``AttributeError`` if no storage object were supplied.
"""
from __future__ import annotations


class InMemoryKeyStorage:
    """Holds the webOS client key in memory only."""

    def __init__(self, client_key: str | None = None) -> None:
        self._key = client_key

    async def get_key(self, key: str) -> str | None:
        return self._key

    async def set_key(self, key: str, value: str) -> None:
        self._key = value
