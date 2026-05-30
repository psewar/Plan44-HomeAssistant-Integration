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

from .const import DOMAIN, SUBENTRY_TYPE_P44_DEVICE, Plan44ConfigEntry
from .coordinator import Plan44Coordinator
from .device_templates import PLATFORM_BINARY_SENSOR, ChannelTemplate
from .inbound import resolve_device

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Plan44ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create binary_sensor entities for binary channels of each p44_device."""
    coordinator = entry.runtime_data.coordinator

    entities: list[Plan44InboundBinarySensorEntity] = []
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_P44_DEVICE:
            continue
        data = getattr(subentry, "data", None)
        if not isinstance(data, Mapping):
            continue
        resolved = resolve_device(data)
        if resolved is None:
            continue
        tag, device_name, channels = resolved
        for channel in channels:
            if channel.platform != PLATFORM_BINARY_SENSOR:
                continue
            entities.append(
                Plan44InboundBinarySensorEntity(
                    coordinator=coordinator,
                    entry_id=entry.entry_id,
                    subentry_id=subentry_id,
                    tag=tag,
                    device_name=device_name,
                    channel=channel,
                )
            )

    if entities:
        async_add_entities(entities)


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
