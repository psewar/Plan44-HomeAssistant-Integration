"""Unit tests for the plan44 web API parsing/mapping (no Home Assistant needed)."""

from __future__ import annotations

from typing import Any

from custom_components.plan44.web_client import (
    PLATFORM_BINARY_SENSOR,
    PLATFORM_SENSOR,
    parse_devices,
    parse_states,
)


def _payload(devices: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap devices in the x-p44-vdcs/x-p44-devices envelope."""
    return {
        "result": {
            "x-p44-vdcs": {
                "vdc0": {"x-p44-devices": {str(i): d for i, d in enumerate(devices)}}
            }
        }
    }


def test_parse_devices_maps_units_and_classes() -> None:
    payload = _payload(
        [
            {
                "dSUID": "AAA",
                "name": "Valve",
                "model": "Micropelt (A5-20-06)",
                "sensorDescriptions": {
                    "temperature": {"sensorType": 1, "siunit": "celsius"},
                    "set_point": {"sensorType": 11, "siunit": "none"},
                },
                "binaryInputDescriptions": {
                    "low_battery": {"sensorFunction": 12},
                },
            }
        ]
    )
    devices = parse_devices(payload)
    assert len(devices) == 1
    dev = devices[0]
    assert dev.dsuid == "AAA"
    assert dev.name == "Valve"
    by_key = {c.key: c for c in dev.channels}

    temp = by_key["temperature"]
    assert temp.platform == PLATFORM_SENSOR
    assert temp.unit == "°C"
    assert temp.device_class == "temperature"
    assert temp.state_class == "measurement"

    sp = by_key["set_point"]
    assert sp.unit is None
    assert sp.device_class is None

    bat = by_key["low_battery"]
    assert bat.platform == PLATFORM_BINARY_SENSOR
    assert bat.device_class == "battery"


def test_parse_devices_energy_is_total_increasing() -> None:
    payload = _payload(
        [
            {
                "dSUID": "P",
                "name": "Plug",
                "model": "",
                "sensorDescriptions": {
                    "energy": {"sensorType": 16, "siunit": "kilowatthour"},
                    "power": {"sensorType": 14, "siunit": "watt"},
                },
            }
        ]
    )
    by_key = {c.key: c for c in parse_devices(payload)[0].channels}
    assert by_key["energy"].unit == "kWh"
    assert by_key["energy"].device_class == "energy"
    assert by_key["energy"].state_class == "total_increasing"
    assert by_key["power"].device_class == "power"


def test_parse_devices_skips_channelless() -> None:
    payload = _payload([{"dSUID": "X", "name": "Light", "model": "Hue"}])
    assert parse_devices(payload) == []


def test_parse_devices_unknown_type_is_plain_sensor() -> None:
    payload = _payload(
        [
            {
                "dSUID": "U",
                "name": "Odd",
                "model": "",
                "sensorDescriptions": {"weird": {"sensorType": 999, "siunit": "xyz"}},
            }
        ]
    )
    ch = parse_devices(payload)[0].channels[0]
    assert ch.platform == PLATFORM_SENSOR
    assert ch.device_class is None
    assert ch.unit is None  # unknown siunit
    assert ch.state_class == "measurement"


def test_parse_states_filters_and_extracts() -> None:
    payload = _payload(
        [
            {
                "dSUID": "AAA",
                "sensorStates": {"temperature": {"value": 21.5}},
                "binaryInputStates": {"low_battery": {"value": False}},
            },
            {
                "dSUID": "BBB",
                "sensorStates": {"temperature": {"value": 9.9}},
            },
        ]
    )
    states = parse_states(payload, {"AAA"})
    assert set(states) == {"AAA"}  # BBB filtered out
    assert states["AAA"][PLATFORM_SENSOR]["temperature"] == 21.5
    assert states["AAA"][PLATFORM_BINARY_SENSOR]["low_battery"] is False


def test_parse_states_missing_value_is_none() -> None:
    payload = _payload([{"dSUID": "AAA", "sensorStates": {"temperature": {}}}])
    states = parse_states(payload, {"AAA"})
    assert states["AAA"][PLATFORM_SENSOR]["temperature"] is None
