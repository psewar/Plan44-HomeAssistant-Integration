from __future__ import annotations

import logging

from homeassistant.components.light import ATTR_BRIGHTNESS
from homeassistant.core import State

from .const import KIND_BINARY_SENSOR, KIND_LIGHT, KIND_SENSOR, KIND_SWITCH
from .plan44_core.models import (
    BinarySensorState,
    DeviceState,
    LightState,
    SensorState,
    SwitchState,
)

_LOGGER = logging.getLogger(__name__)


def ha_state_to_core(kind: str, state: State) -> DeviceState | None:
    """Convert a Home Assistant state into a plan44 core device state.

    Returns ``None`` when the state cannot be represented as the given kind
    (e.g. a sensor whose value is not numeric), signalling the caller to skip
    forwarding instead of raising.
    """
    attributes = state.attributes

    if kind == KIND_SWITCH:
        return SwitchState(is_on=state.state.lower() == "on")
    if kind == KIND_LIGHT:
        brightness_attr = attributes.get(ATTR_BRIGHTNESS)
        brightness = (
            int(brightness_attr) if isinstance(brightness_attr, (int, float)) else None
        )
        return LightState(
            is_on=state.state.lower() == "on",
            brightness=brightness,
        )
    if kind == KIND_BINARY_SENSOR:
        return BinarySensorState(is_on=state.state.lower() == "on")
    if kind == KIND_SENSOR:
        try:
            return SensorState(numeric_value=float(state.state))
        except ValueError, TypeError:
            _LOGGER.warning(
                "Sensor %s has non-numeric state '%s', skipping forward sync",
                state.entity_id,
                state.state,
            )
            return None
    return None
