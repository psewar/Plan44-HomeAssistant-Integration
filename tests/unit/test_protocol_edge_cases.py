from __future__ import annotations

import logging

import pytest
from plan44_core.models import (
    BinarySensorState,
    DeviceState,
    LightState,
    SwitchState,
    VirtualDeviceSpec,
)
from plan44_core.protocol import (
    LIGHT_ON_THRESHOLD,
    P44_MAX_CHANNEL_VALUE,
    build_channel_message,
    build_init_message,
    build_input_message,
    build_sensor_message,
    light_state_to_p44_value,
    p44_value_to_brightness,
    parse_incoming_message,
    state_to_messages,
)


def _sensor_type_for_unit(unit: str | None) -> int:
    """Resolve the P44 sensortype for a unit through the public init message."""
    spec = VirtualDeviceSpec(
        device_id="ha::sensor.x", name="Sensor", kind="sensor", unit=unit
    )
    return build_init_message(spec)["sensors"][0]["sensortype"]


# --- light_state_to_p44_value -------------------------------------------------


def test_light_off_maps_to_zero() -> None:
    assert light_state_to_p44_value(LightState(is_on=False, brightness=200)) == 0


def test_light_on_without_brightness_maps_to_full() -> None:
    value = light_state_to_p44_value(LightState(is_on=True, brightness=None))
    assert value == P44_MAX_CHANNEL_VALUE


def test_light_full_brightness_maps_to_max() -> None:
    assert light_state_to_p44_value(LightState(is_on=True, brightness=255)) == 100


def test_low_brightness_clamps_to_threshold_so_light_stays_on() -> None:
    # brightness=1 scales to 0, but an "on" light must never report 0 to P44.
    value = light_state_to_p44_value(LightState(is_on=True, brightness=1))
    assert value == LIGHT_ON_THRESHOLD


def test_over_range_brightness_clamps_to_max() -> None:
    value = light_state_to_p44_value(LightState(is_on=True, brightness=999))
    assert value == P44_MAX_CHANNEL_VALUE


# --- p44_value_to_brightness --------------------------------------------------


def test_p44_zero_maps_to_zero_brightness() -> None:
    assert p44_value_to_brightness(0) == 0


def test_p44_full_maps_to_max_brightness() -> None:
    assert p44_value_to_brightness(100) == 255


def test_p44_small_value_keeps_minimum_brightness_of_one() -> None:
    assert p44_value_to_brightness(1) >= 1


@pytest.mark.parametrize("value", [-5, 150])
def test_p44_value_is_clamped_to_valid_range(value: int) -> None:
    result = p44_value_to_brightness(value)
    assert 0 <= result <= 255


def test_brightness_roundtrip_is_stable_for_mid_value() -> None:
    original = 128
    p44 = light_state_to_p44_value(LightState(is_on=True, brightness=original))
    assert p44_value_to_brightness(p44) == original


# --- parse_incoming_message ---------------------------------------------------


def test_parse_ignores_non_channel_message() -> None:
    assert parse_incoming_message({"message": "sensor", "tag": "x"}, "switch") is None


def test_parse_ignores_message_without_tag() -> None:
    msg = {"message": "channel", "value": 100}
    assert parse_incoming_message(msg, "switch") is None


def test_parse_switch_off() -> None:
    cmd = parse_incoming_message(
        {"message": "channel", "tag": "ha::switch.x", "value": 0}, "switch"
    )
    assert cmd is not None
    assert cmd.action == "turn_off"


def test_parse_light_turn_off_on_zero() -> None:
    cmd = parse_incoming_message(
        {"message": "channel", "tag": "ha::light.x", "value": 0}, "light"
    )
    assert cmd is not None
    assert cmd.action == "turn_off"
    assert cmd.value is None


def test_parse_light_set_brightness() -> None:
    cmd = parse_incoming_message(
        {"message": "channel", "tag": "ha::light.x", "value": 50}, "light"
    )
    assert cmd is not None
    assert cmd.action == "set_brightness"
    assert cmd.value == p44_value_to_brightness(50)


@pytest.mark.parametrize("kind", ["sensor", "binary_sensor"])
def test_parse_returns_none_for_forward_only_kinds(kind: str) -> None:
    msg = {"message": "channel", "tag": "ha::x", "value": 100}
    assert parse_incoming_message(msg, kind) is None  # type: ignore[arg-type]


# --- build_channel_message ----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(-10, 0), (0, 0), (50, 50), (100, 100), (250, 100)],
)
def test_channel_message_clamps_value(raw: int, expected: int) -> None:
    msg = build_channel_message("ha::switch.x", raw)
    assert msg["message"] == "channel"
    assert msg["value"] == expected


def test_input_message_normalizes_to_zero_or_one() -> None:
    assert build_input_message("ha::binary_sensor.x", True)["value"] == 1
    assert build_input_message("ha::binary_sensor.x", False)["value"] == 0
    assert build_input_message("ha::binary_sensor.x", 5)["value"] == 1


def test_sensor_message_preserves_float() -> None:
    msg = build_sensor_message("ha::sensor.x", 21.5)
    assert msg["message"] == "sensor"
    assert msg["value"] == 21.5


# --- state_to_messages --------------------------------------------------------


def test_switch_state_to_channel_messages() -> None:
    assert state_to_messages("x", SwitchState(is_on=True))[0]["value"] == 100
    assert state_to_messages("x", SwitchState(is_on=False))[0]["value"] == 0


def test_binary_sensor_state_to_input_message() -> None:
    messages = state_to_messages("x", BinarySensorState(is_on=True))
    assert messages[0]["message"] == "input"


def test_unsupported_state_type_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported state type"):
        state_to_messages("x", DeviceState())


# --- sensor unit defaults (via public build_init_message) ---------------------


@pytest.mark.parametrize(
    ("unit", "expected_type"),
    [
        ("°C", 1),
        ("c", 1),
        ("degC", 1),
        ("%", 2),
        ("percent", 2),
        ("W", 14),
        ("watt", 14),
        ("hPa", 18),
        ("mbar", 18),
    ],
)
def test_known_units_map_to_expected_sensor_type(unit: str, expected_type: int) -> None:
    assert _sensor_type_for_unit(unit) == expected_type


def test_unknown_unit_falls_back_to_generic_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="plan44_core.protocol"):
        sensortype = _sensor_type_for_unit("lux")
    assert sensortype == 0
    assert any("Unknown sensor unit" in record.message for record in caplog.records)


@pytest.mark.parametrize("unit", [None, ""])
def test_missing_unit_uses_generic_without_warning(
    unit: str | None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="plan44_core.protocol"):
        sensortype = _sensor_type_for_unit(unit)
    assert sensortype == 0
    assert not caplog.records


# --- build_init_message -------------------------------------------------------


def test_sensor_init_honours_explicit_overrides() -> None:
    spec = VirtualDeviceSpec(
        device_id="ha::sensor.custom",
        name="Custom",
        kind="sensor",
        unit="°C",
        sensor_type=99,
        sensor_min=-40.0,
        sensor_max=125.0,
        sensor_resolution=0.5,
    )
    sensor_def = build_init_message(spec)["sensors"][0]
    assert sensor_def["sensortype"] == 99
    assert sensor_def["min"] == -40.0
    assert sensor_def["max"] == 125.0
    assert sensor_def["resolution"] == 0.5


def test_unsupported_kind_raises() -> None:
    spec = VirtualDeviceSpec(device_id="x", name="x", kind="cover")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="Unsupported device kind"):
        build_init_message(spec)
