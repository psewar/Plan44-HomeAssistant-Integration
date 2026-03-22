from __future__ import annotations

from plan44_core.models import (
    BinarySensorState,
    LightState,
    SensorState,
    VirtualDeviceSpec,
)
from plan44_core.protocol import (
    build_init_message,
    light_state_to_p44_value,
    p44_value_to_brightness,
    parse_incoming_message,
    state_to_messages,
)


def test_switch_init_message() -> None:
    spec = VirtualDeviceSpec(device_id="ha::switch.test", name="Test", kind="switch")
    payload = build_init_message(spec)
    assert payload["message"] == "init"
    assert payload["output"] == "light"
    assert payload["tag"] == "ha::switch.test"


def test_light_init_message() -> None:
    spec = VirtualDeviceSpec(device_id="ha::light.test", name="Light", kind="light")
    payload = build_init_message(spec)
    assert payload["message"] == "init"
    assert payload["output"] == "light"
    assert payload["tag"] == "ha::light.test"


def test_binary_sensor_init_message() -> None:
    spec = VirtualDeviceSpec(
        device_id="ha::binary_sensor.contact",
        name="Contact",
        kind="binary_sensor",
    )
    payload = build_init_message(spec)
    assert payload["message"] == "init"
    assert payload["uniqueid"] == "ha::binary_sensor.contact"
    input_def = payload["inputs"][0]
    assert input_def["inputtype"] == 0
    assert input_def["usage"] == 2
    assert input_def["group"] == 8


def test_sensor_init_message_uses_sensors_array() -> None:
    spec = VirtualDeviceSpec(
        device_id="ha::sensor.temp",
        name="Temp",
        kind="sensor",
        unit="°C",
    )
    payload = build_init_message(spec)
    assert payload["protocol"] == "simple"
    sensor_def = payload["sensors"][0]
    assert sensor_def["sensortype"] == 1
    assert sensor_def["hardwarename"] == "Temp"
    assert sensor_def["resolution"] == 0.1


def test_light_brightness_roundtrip() -> None:
    state = LightState(is_on=True, brightness=128)
    value = light_state_to_p44_value(state)
    assert value == 50
    brightness = p44_value_to_brightness(value)
    assert brightness == 128


def test_sensor_state_becomes_sensor_message() -> None:
    spec = VirtualDeviceSpec(device_id="ha::sensor.temp", name="Temp", kind="sensor")
    messages = state_to_messages(spec.device_id, SensorState(numeric_value=21.5))
    assert messages[0]["message"] == "sensor"
    assert messages[0]["value"] == 21.5


def test_binary_sensor_state_becomes_input_message() -> None:
    spec = VirtualDeviceSpec(
        device_id="ha::binary_sensor.contact",
        name="Contact",
        kind="binary_sensor",
    )
    messages = state_to_messages(spec.device_id, BinarySensorState(is_on=True))
    assert messages[0]["message"] == "input"
    assert messages[0]["value"] == 1


def test_parse_channel_message() -> None:
    incoming = {
        "message": "channel",
        "tag": "ha::switch.test",
        "index": 0,
        "value": 100,
    }
    cmd = parse_incoming_message(incoming, "switch")
    assert cmd is not None
    assert cmd.device_id == "ha::switch.test"
    assert cmd.action == "turn_on"
    assert cmd.value is None
