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
    assert p44_value_to_brightness(value) == 128


def test_state_to_messages_for_sensor() -> None:
    messages = state_to_messages("ha::sensor.temp", SensorState(numeric_value=21.5))
    assert messages == [
        {"message": "sensor", "tag": "ha::sensor.temp", "index": 0, "value": 21.5}
    ]


def test_state_to_messages_for_binary_sensor() -> None:
    messages = state_to_messages(
        "ha::binary_sensor.contact",
        BinarySensorState(is_on=True),
    )
    assert messages == [
        {
            "message": "input",
            "tag": "ha::binary_sensor.contact",
            "index": 0,
            "value": 1,
        }
    ]


def test_parse_incoming_light_command() -> None:
    command = parse_incoming_message(
        {"message": "channel", "tag": "ha::light.test", "index": 0, "value": 100},
        "light",
    )
    assert command is not None
    assert command.action == "set_brightness"
    assert command.value == 255
