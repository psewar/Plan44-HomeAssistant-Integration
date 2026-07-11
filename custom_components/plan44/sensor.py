from __future__ import annotations

import logging
from collections.abc import Mapping
from decimal import Decimal
from functools import cached_property
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import (
    ATTR_CHANNELS,
    ATTR_DSUID,
    ATTR_MODEL,
    ATTR_NAME,
    DOMAIN,
    Plan44ConfigEntry,
)
from .coordinator import Plan44Coordinator
from .device_coordinator import Plan44DeviceCoordinator
from .device_templates import PLATFORM_SENSOR, ChannelTemplate
from .inbound import resolve_device, setup_p44_device_entities

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Plan44ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Create sensor entities for the sensor channels of each p44_device.

    Two kinds of p44_device subentry are supported:
    * dSUID-based (discovered via the REST web API) → polled CoordinatorEntity
    * tag-based (manual/template) → push entity fed by the TCP coordinator

    Entities are added under their own subentry (``config_subentry_id``) so the
    imported device is attributed to its "Plan44 device" sub-entry in the UI
    instead of the generic "devices that don't belong to a sub-entry" bucket.
    """
    setup_p44_device_entities(
        entry,
        async_add_entities,
        _build_rest_sensors,
        _build_push_sensors,
    )


def _build_rest_sensors(
    coordinator: Plan44DeviceCoordinator,
    entry_id: str,
    subentry_id: str,
    data: Mapping[str, Any],
) -> list[SensorEntity]:
    dsuid = str(data[ATTR_DSUID])
    device_name = str(data.get(ATTR_NAME) or dsuid)
    model = str(data.get(ATTR_MODEL) or "") or None
    out: list[SensorEntity] = []
    for ch in data.get(ATTR_CHANNELS, []):
        if not isinstance(ch, Mapping) or ch.get("platform") != PLATFORM_SENSOR:
            continue
        out.append(
            Plan44RestSensor(
                coordinator, entry_id, subentry_id, dsuid, device_name, model, ch
            )
        )
    return out


def _build_push_sensors(
    coordinator: Plan44Coordinator,
    entry_id: str,
    subentry_id: str,
    data: Mapping[str, Any],
) -> list[SensorEntity]:
    resolved = resolve_device(data)
    if resolved is None:
        _LOGGER.warning("p44_device subentry %s has no valid tag", subentry_id)
        return []
    tag, device_name, channels = resolved
    return [
        Plan44InboundSensorEntity(
            coordinator, entry_id, subentry_id, tag, device_name, ch
        )
        for ch in channels
        if ch.platform == PLATFORM_SENSOR
    ]


class Plan44RestSensor(SensorEntity):
    """A sensor polled from the plan44 web API for a discovered device channel."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Plan44DeviceCoordinator,
        entry_id: str,
        subentry_id: str,
        dsuid: str,
        device_name: str,
        model: str | None,
        channel: Mapping[str, Any],
    ) -> None:
        self._coordinator = coordinator
        self._dsuid = dsuid
        self._key = str(channel["key"])
        self._attr_name = channel.get("name")
        self._attr_native_unit_of_measurement = channel.get("unit")
        self._attr_unique_id = f"{entry_id}_{subentry_id}_{self._key}"
        self._attr_native_value = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, dsuid)},
            name=device_name,
            model=model,
            manufacturer="plan44",
        )
        dc = channel.get("device_class")
        if dc:
            try:
                self._attr_device_class = SensorDeviceClass(dc)
            except ValueError:
                _LOGGER.warning("Unknown device_class '%s' — ignoring", dc)
        sc = channel.get("state_class")
        if sc:
            try:
                self._attr_state_class = SensorStateClass(sc)
            except ValueError:
                pass

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._coordinator.async_add_listener(self._handle_update))
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        device = (self._coordinator.data or {}).get(self._dsuid)
        value = device.get(PLATFORM_SENSOR, {}).get(self._key) if device else None
        self._attr_native_value = value if isinstance(value, (int, float)) else None
        self._attr_available = (
            self._coordinator.last_update_success and device is not None
        )
        self.async_write_ha_state()

    @cached_property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return {"p44_dsuid": self._dsuid, "p44_channel": self._key}


class Plan44InboundSensorEntity(SensorEntity):
    """A sensor whose value is pushed by plan44 for a physical-device channel."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Plan44Coordinator,
        entry_id: str,
        subentry_id: str,
        tag: str,
        device_name: str,
        channel: ChannelTemplate,
    ) -> None:
        self._coordinator = coordinator
        self._tag = tag
        self._channel = channel
        self._attr_name = channel.name
        self._attr_native_unit_of_measurement = channel.unit
        self._attr_unique_id = f"{entry_id}_{subentry_id}_{channel.key}"
        self._attr_native_value = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tag)},
            name=device_name,
            manufacturer="plan44",
        )
        if channel.device_class:
            try:
                self._attr_device_class = SensorDeviceClass(channel.device_class)
            except ValueError:
                _LOGGER.warning(
                    "Unknown sensor device_class '%s' for %s — ignoring",
                    channel.device_class,
                    self._attr_unique_id,
                )
        if channel.state_class:
            try:
                self._attr_state_class = SensorStateClass(channel.state_class)
            except ValueError:
                pass

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._coordinator.register_inbound_callback(
            self._channel.message, self._tag, self._channel.index, self._on_value
        )

    async def async_will_remove_from_hass(self) -> None:
        self._coordinator.unregister_inbound_callback(
            self._channel.message, self._tag, self._channel.index
        )
        await super().async_will_remove_from_hass()

    @callback
    def _on_value(self, value: float) -> None:
        self._attr_native_value = Decimal(str(value))
        self.async_write_ha_state()

    @cached_property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return {"p44_tag": self._tag, "p44_index": self._channel.index}
