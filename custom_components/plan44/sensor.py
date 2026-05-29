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
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    ATTR_DEVICE_CLASS,
    ATTR_NAME,
    ATTR_P44_INDEX,
    ATTR_P44_TAG,
    ATTR_UNIT,
    SUBENTRY_TYPE_P44_SENSOR,
    Plan44ConfigEntry,
)
from .coordinator import Plan44Coordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: Plan44ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up plan44 inbound sensor entities from p44_sensor subentries."""
    coordinator: Plan44Coordinator = entry.runtime_data.coordinator

    entities: list[Plan44InboundSensorEntity] = []
    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_P44_SENSOR:
            continue
        data = getattr(subentry, "data", None)
        if not isinstance(data, Mapping):
            continue
        tag = data.get(ATTR_P44_TAG)
        if not isinstance(tag, str) or not tag:
            _LOGGER.warning(
                "p44_sensor subentry %s is missing a valid p44_tag — skipping",
                subentry_id,
            )
            continue
        entities.append(
            Plan44InboundSensorEntity(
                coordinator=coordinator,
                entry_id=entry.entry_id,
                subentry_id=subentry_id,
                tag=tag,
                index=int(data.get(ATTR_P44_INDEX, 0)),
                name=str(data.get(ATTR_NAME) or tag),
                unit=str(data[ATTR_UNIT]) if data.get(ATTR_UNIT) else None,
                device_class=str(data[ATTR_DEVICE_CLASS])
                if data.get(ATTR_DEVICE_CLASS)
                else None,
            )
        )

    if entities:
        async_add_entities(entities)


class Plan44InboundSensorEntity(SensorEntity):
    """A Home Assistant sensor entity whose value is pushed by plan44.

    Unlike exported virtual devices (which flow HA → P44), inbound sensors
    flow P44 → HA: plan44 pushes physical-device sensor readings
    (e.g. EnOcean D2-14-41 acceleration channels) to this entity via TCP.
    """

    _attr_should_poll = False
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: Plan44Coordinator,
        entry_id: str,
        subentry_id: str,
        tag: str,
        index: int,
        name: str,
        unit: str | None,
        device_class: str | None,
    ) -> None:
        self._coordinator = coordinator
        self._tag = tag
        self._index = index
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_unique_id = f"{entry_id}_{subentry_id}"
        # Do not annotate _attr_native_value — use the base-class type
        # (StateType | date | datetime | Decimal | None).  We only write
        # Decimal values so the display has consistent precision.
        self._attr_native_value = None

        if device_class:
            try:
                self._attr_device_class = SensorDeviceClass(device_class)
            except ValueError:
                _LOGGER.warning(
                    "Unknown device class '%s' for plan44 sensor '%s' — ignoring",
                    device_class,
                    name,
                )

    async def async_added_to_hass(self) -> None:
        self._coordinator.register_inbound_sensor_callback(
            self._tag, self._index, self._handle_value
        )
        _LOGGER.debug(
            "Registered plan44 inbound sensor: tag=%s index=%s",
            self._tag,
            self._index,
        )

    async def async_will_remove_from_hass(self) -> None:
        self._coordinator.unregister_inbound_sensor_callback(self._tag, self._index)

    @callback
    def _handle_value(self, value: float) -> None:
        """Receive a sensor push from plan44 and update HA state."""
        self._attr_native_value = Decimal(str(value))
        self.async_write_ha_state()

    @cached_property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        # Tag and index are immutable after init — cached_property is safe here.
        return {"p44_tag": self._tag, "p44_index": self._index}
