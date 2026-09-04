"""Tests for state_mapping.ha_state_to_core.

The function is a pure HA-state -> core-state mapping and needs no running
Home Assistant, so the tests construct State objects directly.
"""

from __future__ import annotations

import logging

import pytest
from homeassistant.components.light import ATTR_BRIGHTNESS
from homeassistant.core import State

from custom_components.plan44.plan44_core.models import (
    BinarySensorState,
    LightState,
    SensorState,
    SwitchState,
)
from custom_components.plan44.state_mapping import ha_state_to_core


def test_switch_on_maps_to_switch_state() -> None:
    assert ha_state_to_core("switch", State("switch.x", "on")) == SwitchState(
        is_on=True
    )


def test_switch_off_maps_to_switch_state() -> None:
    result = ha_state_to_core("switch", State("switch.x", "off"))
    assert result == SwitchState(is_on=False)


def test_binary_sensor_maps_to_binary_sensor_state() -> None:
    result = ha_state_to_core("binary_sensor", State("binary_sensor.x", "on"))
    assert result == BinarySensorState(is_on=True)


def test_light_with_brightness_maps_to_light_state() -> None:
    state = State("light.x", "on", {ATTR_BRIGHTNESS: 200})
    result = ha_state_to_core("light", state)
    assert isinstance(result, LightState)
    assert result.is_on is True
    assert result.brightness == 200


def test_light_without_brightness_attribute() -> None:
    result = ha_state_to_core("light", State("light.x", "on"))
    assert isinstance(result, LightState)
    assert result.brightness is None


def test_numeric_sensor_maps_to_sensor_state() -> None:
    result = ha_state_to_core("sensor", State("sensor.temp", "21.5"))
    assert isinstance(result, SensorState)
    assert result.numeric_value == 21.5


def test_non_numeric_sensor_is_skipped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        result = ha_state_to_core("sensor", State("sensor.broken", "unavailable"))
    assert result is None
    assert any("non-numeric state" in record.message for record in caplog.records)


def test_unknown_kind_returns_none() -> None:
    assert ha_state_to_core("cover", State("cover.x", "open")) is None
