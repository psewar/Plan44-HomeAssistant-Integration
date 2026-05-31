from __future__ import annotations

import logging
from collections.abc import Mapping
from functools import cached_property
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_CHANNELS,
    ATTR_DSUID,
    ATTR_MODEL,
    ATTR_NAME,
    DOMAIN,
    SUBENTRY_TYPE_P44_DEVICE,
    Plan44ConfigEntry,
)
from .coordinator import Plan44Coordinator
from .device_coordinator import Plan44DeviceCoordinator
from .device_templates import PLATFORM_BINARY_SENSOR, ChannelTemplate
from .inbound import resolve_device

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Plan44ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create binary_sensor entities for the binary channels of each p44_device."""
    runtime = entry.runtime_data
    entities: list[BinarySensorEntity] = []

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_P44_DEVICE:
            continue
        data = getattr(subentry, "data", None)
        if not isinstance(data, Mapping):
            continue

        if data.get(ATTR_DSUID):
            if runtime.device_coordinator is None:
                continue
            entities.extend(
                _build_rest_inputs(
                    runtime.device_coordinator, entry.entry_id, subentry_id, data
                )
            )
        else:
            entities.extend(
                _build_push_inputs(
                    runtime.coordinator, entry.entry_id, subentry_id, data
                )
            )

    if entities:
        async_add_entities(entities)


def _build_rest_inputs(
    coordinator: Plan44DeviceCoordinator,
    entry_id: str,
    subentry_id: str,
    data: Mapping[str, Any],
) -> list[BinarySensorEntity]:
    dsuid = str(data[ATTR_DSUID])
    device_name = str(data.get(ATTR_NAME) or dsuid)
    model = str(data.get(ATTR_MODEL) or "") or None
    out: list[BinarySensorEntity] = []
    for ch in data.get(ATTR_CHANNELS, []):
        if not isinstance(ch, Mapping) or ch.get("platform") != PLATFORM_BINARY_SENSOR:
            continue
        out.append(
            Plan44RestBinarySensor(
                coordinator, entry_id, subentry_id, dsuid, device_name, model, ch
            )
        )
    return out


def _build_push_inputs(
    coordinator: Plan44Coordinator,
    entry_id: str,
    subentry_id: str,
    data: Mapping[str, Any],
) -> list[BinarySensorEntity]:
    resolved = resolve_device(data)
    if resolved is None:
        return []
    tag, device_name, channels = resolved
    return [
        Plan44InboundBinarySensorEntity(
            coordinator, entry_id, subentry_id, tag, device_name, ch
        )
        for ch in channels
        if ch.platform == PLATFORM_BINARY_SENSOR
    ]


class Plan44RestBinarySensor(BinarySensorEntity):
    """A binary sensor polled from the plan44 web API for a discovered channel."""

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
        self._attr_unique_id = f"{entry_id}_{subentry_id}_{self._key}"
        self._attr_is_on = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, dsuid)},
            name=device_name,
            model=model,
            manufacturer="plan44",
        )
        dc = channel.get("device_class")
        if dc:
            try:
                self._attr_device_class = BinarySensorDeviceClass(dc)
            except ValueError:
                _LOGGER.warning("Unknown device_class '%s' — ignoring", dc)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._coordinator.async_add_listener(self._handle_update))
        self._handle_update()

    @callback
    def _handle_update(self) -> None:
        device = (self._coordinator.data or {}).get(self._dsuid)
        value = (
            device.get(PLATFORM_BINARY_SENSOR, {}).get(self._key) if device else None
        )
        self._attr_is_on = bool(value) if value is not None else None
        self._attr_available = (
            self._coordinator.last_update_success and device is not None
        )
        self.async_write_ha_state()

    @cached_property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return {"p44_dsuid": self._dsuid, "p44_channel": self._key}


class Plan44InboundBinarySensorEntity(BinarySensorEntity):
    """A binary sensor whose state is pushed by plan44 (input channel)."""

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
        self._attr_unique_id = f"{entry_id}_{subentry_id}_{channel.key}"
        self._attr_is_on = None
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, tag)},
            name=device_name,
            manufacturer="plan44",
        )
        if channel.device_class:
            try:
                self._attr_device_class = BinarySensorDeviceClass(channel.device_class)
            except ValueError:
                _LOGGER.warning(
                    "Unknown binary_sensor device_class '%s' for %s — ignoring",
                    channel.device_class,
                    self._attr_unique_id,
                )

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
        self._attr_is_on = value != 0
        self.async_write_ha_state()

    @cached_property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        return {"p44_tag": self._tag, "p44_index": self._channel.index}
