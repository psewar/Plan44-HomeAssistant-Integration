from __future__ import annotations

from collections.abc import Iterator
from typing import TypedDict

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORE_KEY_EXPORTS, STORE_VERSION


class ExportRecord(TypedDict):
    uid: str
    kind: str
    name: str
    room_hint: str | None
    allow_reverse: bool
    enabled: bool
    source_domain: str | None


class StoreData(TypedDict):
    exports: dict[str, ExportRecord]


class Plan44Store:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._store = Store[StoreData](
            hass,
            STORE_VERSION,
            f"{DOMAIN}_{entry.entry_id}.json",
        )
        self.data: StoreData = {
            STORE_KEY_EXPORTS: {},
        }

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if stored is not None:
            self.data = stored

    async def async_save(self) -> None:
        await self._store.async_save(self.data)

    def get_export(self, entity_id: str) -> ExportRecord | None:
        return self.data[STORE_KEY_EXPORTS].get(entity_id)

    def get_export_by_uid(
        self,
        uid: str,
    ) -> tuple[str | None, ExportRecord | None]:
        for entity_id, cfg in self.data[STORE_KEY_EXPORTS].items():
            if cfg["uid"] == uid:
                return entity_id, cfg
        return None, None

    async def async_add_export(
        self,
        entity_id: str,
        uid: str,
        kind: str,
        name: str,
        room_hint: str | None,
        allow_reverse: bool,
        source_domain: str | None,
    ) -> None:
        self.data[STORE_KEY_EXPORTS][entity_id] = {
            "uid": uid,
            "kind": kind,
            "name": name,
            "room_hint": room_hint,
            "allow_reverse": allow_reverse,
            "enabled": True,
            "source_domain": source_domain,
        }
        await self.async_save()

    async def async_remove_export(self, entity_id: str) -> None:
        self.data[STORE_KEY_EXPORTS].pop(entity_id, None)
        await self.async_save()

    def iter_exports(self) -> Iterator[tuple[str, ExportRecord]]:
        return iter(self.data[STORE_KEY_EXPORTS].items())
