"""Diagnostic entities for the radio link of the bridge's wireless devices.

With the radio diagnostics option on, every device the bridge tracks radio
packets for (EnOcean, and likewise ELDAT and ZF) gets a few diagnostic
entities: signal strength, repeaters, last radio packet, the bridge's active
flag, its operating-state text and, where the device has one, its low-battery
input (an energy-harvesting valve's energy store).  They do not depend on the
device being imported: a heating valve that Home Assistant otherwise only sees
through digitalSTROM still shows when it last transmitted.  That is the one
thing the digitalSTROM side cannot tell — it keeps mirroring the zone
temperature while the valve itself has gone silent.

An imported device gets them on its own device and sub-entry; every other one
gets a diagnostics-only device.  The platforms only supply their entity
classes; discovery and device attribution live here.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import (
    ATTR_DSUID,
    ATTR_MODEL,
    ATTR_NAME,
    ATTR_VENDOR,
    DEVICE_RADIO,
    DOMAIN,
    SUBENTRY_TYPE_P44_DEVICE,
)
from .web_client import RadioState

if TYPE_CHECKING:
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from .const import Plan44ConfigEntry
    from .device_coordinator import Plan44DeviceCoordinator


def _imported_devices(
    entry: Plan44ConfigEntry,
) -> dict[str, tuple[str, Mapping[str, Any]]]:
    """dSUID -> (sub-entry id, sub-entry data) of every picker-imported device."""
    imported: dict[str, tuple[str, Mapping[str, Any]]] = {}
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_P44_DEVICE:
            continue
        data = getattr(subentry, "data", None)
        if isinstance(data, Mapping) and data.get(ATTR_DSUID):
            imported[str(data[ATTR_DSUID])] = (subentry_id, data)
    return imported


def radio_device_info(
    radio: RadioState, imported: Mapping[str, Any] | None
) -> DeviceInfo:
    """DeviceInfo for a radio device, matching its import if it has one.

    An imported device is described exactly as its channel entities describe
    it (sub-entry name, model, vendor), so the two never fight over the device
    name.  Any other device is named as the bridge names it.
    """
    if imported is not None:
        return DeviceInfo(
            identifiers={(DOMAIN, radio.dsuid)},
            name=str(imported.get(ATTR_NAME) or radio.dsuid),
            model=str(imported.get(ATTR_MODEL) or "") or None,
            manufacturer=str(imported.get(ATTR_VENDOR) or "") or "plan44",
        )
    return DeviceInfo(
        identifiers={(DOMAIN, radio.dsuid)},
        name=radio.name,
        model=radio.model or None,
        manufacturer="plan44",
    )


def setup_radio_entities[EntityT: Entity](
    entry: Plan44ConfigEntry,
    add_entities: AddConfigEntryEntitiesCallback,
    build: Callable[
        [Plan44DeviceCoordinator, str, RadioState, DeviceInfo, bool], list[EntityT]
    ],
) -> None:
    """Add the radio diagnostics of every radio device, now and as more appear.

    A device learned into the bridge later shows up with the next poll, no
    reload needed.  Each device goes to its import sub-entry when it has one,
    so it does not also land among "devices that don't belong to a sub-entry".
    ``build`` is told whether the device is imported, so it can leave out what
    the import already shows as a channel.
    """
    coordinator = entry.runtime_data.device_coordinator
    if coordinator is None or not coordinator.radio_diagnostics:
        return
    imported = _imported_devices(entry)
    added: set[str] = set()

    @callback
    def _add_new_devices() -> None:
        for dsuid, device in (coordinator.data or {}).items():
            radio = device.get(DEVICE_RADIO)
            if dsuid in added or not isinstance(radio, RadioState):
                continue
            added.add(dsuid)
            subentry = imported.get(dsuid)
            entities = build(
                coordinator,
                entry.entry_id,
                radio,
                radio_device_info(radio, subentry[1] if subentry else None),
                subentry is not None,
            )
            add_entities(entities, config_subentry_id=subentry[0] if subentry else None)

    _add_new_devices()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_devices))


class Plan44RadioEntity(Entity):
    """One radio-link diagnostic of one bridge device, read from the poll.

    Subclasses set ``_attr_translation_key``, which doubles as the stable
    suffix of the unique ID, and copy their value in ``_update_from_radio``.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        coordinator: Plan44DeviceCoordinator,
        entry_id: str,
        radio: RadioState,
        device_info: DeviceInfo,
    ) -> None:
        self._coordinator = coordinator
        self._dsuid = radio.dsuid
        # Keyed by dSUID, not sub-entry: the diagnostics exist whether or not
        # the device is imported, and keep their history when it is imported.
        self._attr_unique_id = f"{entry_id}_{radio.dsuid}_{self._attr_translation_key}"
        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._coordinator.async_add_listener(self._handle_update))
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        device = (self._coordinator.data or {}).get(self._dsuid) or {}
        radio = device.get(DEVICE_RADIO)
        # Available while the bridge answers and still lists the device. A
        # silent or inactive device stays available on purpose: that is the
        # very fact these entities are there to show.
        self._attr_available = self._coordinator.last_update_success and isinstance(
            radio, RadioState
        )
        if isinstance(radio, RadioState):
            self._update_from_radio(radio)
        self.async_write_ha_state()

    @callback
    def _update_from_radio(self, radio: RadioState) -> None:
        """Copy this entity's value out of the latest poll (subclasses)."""
