from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .const import (
    CONF_VDC_MODEL_NAME,
    DOMAIN,
    Plan44ConfigEntry,
    signal_bridge_connection,
)

if TYPE_CHECKING:
    from .coordinator import Plan44Coordinator


def bridge_device_info(entry: Plan44ConfigEntry) -> DeviceInfo:
    """DeviceInfo for the plan44 bridge itself (host of the diagnostic entities)."""
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="plan44 Bridge",
        manufacturer="plan44",
        model=entry.data.get(CONF_VDC_MODEL_NAME),
    )


class Plan44BridgeEntity(Entity):
    """Base for diagnostic entities describing the bridge connection itself.

    These are not tied to a p44 device sub-entry; they live on a dedicated
    "plan44 Bridge" device and refresh whenever the coordinator broadcasts a
    connection-state change.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: Plan44ConfigEntry) -> None:
        self._entry = entry
        self._attr_device_info = bridge_device_info(entry)

    @property
    def _coordinator(self) -> Plan44Coordinator:
        return self._entry.runtime_data.coordinator

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._update_from_coordinator()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_bridge_connection(self._entry.entry_id),
                self._handle_connection_signal,
            )
        )

    @callback
    def _handle_connection_signal(self) -> None:
        self._update_from_coordinator()
        self.async_write_ha_state()

    @callback
    def _update_from_coordinator(self) -> None:
        """Refresh ``_attr_*`` values from coordinator/client state (subclasses)."""
