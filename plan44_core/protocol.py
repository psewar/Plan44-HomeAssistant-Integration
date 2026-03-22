from __future__ import annotations

from typing import Any, Protocol

from .models import (
    BinarySensorState,
    DeviceCommand,
    DeviceKind,
    DeviceState,
    LightState,
    SensorState,
    SwitchState,
    VirtualDeviceSpec,
)

LIGHT_MAX_BRIGHTNESS = 255
P44_MAX_CHANNEL_VALUE = 100
LIGHT_ON_THRESHOLD = 1


class SupportsInitSpec(Protocol):
    tag: str
    name: str
    kind: DeviceKind
    unit: str | None
    model: str | None
    iconname: str
    sync: bool
    uniqueid: str
    sensor_type: int | None
    sensor_usage: int
    sensor_min: float | None
    sensor_max: float | None
    sensor_resolution: float | None
    sensor_update_interval: int | None
    sensor_alive_sign_interval: int | None


def build_initvdc_message(model_name: str) -> dict[str, Any]:
    return {"message": "initvdc", "model": model_name}


def build_init_message(spec: SupportsInitSpec | VirtualDeviceSpec) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "message": "init",
        "tag": spec.tag,
        "name": spec.name,
        "model": spec.model or _default_model_for_kind(spec.kind),
        "iconname": spec.iconname,
        "sync": spec.sync,
        "uniqueid": spec.uniqueid,
    }

    if spec.kind in {"switch", "light"}:
        payload["output"] = "light"
    elif spec.kind == "binary_sensor":
        payload["output"] = "switch"
    elif spec.kind == "sensor":
        payload["protocol"] = "simple"
        payload["sensors"] = [_build_sensor_definition(spec)]
    else:
        raise ValueError(f"Unsupported device kind: {spec.kind}")

    return payload


def build_channel_message(
    device_id: str,
    value: int,
    index: int = 0,
) -> dict[str, Any]:
    return {
        "message": "channel",
        "tag": device_id,
        "index": index,
        "value": max(0, min(P44_MAX_CHANNEL_VALUE, int(value))),
    }


def build_sensor_message(
    device_id: str,
    value: float,
    index: int = 0,
) -> dict[str, Any]:
    return {
        "message": "sensor",
        "tag": device_id,
        "index": index,
        "value": float(value),
    }


def state_to_messages(device_id: str, state: DeviceState) -> list[dict[str, Any]]:
    if isinstance(state, SwitchState):
        return [build_channel_message(device_id, 100 if state.is_on else 0)]
    if isinstance(state, BinarySensorState):
        return [build_channel_message(device_id, 100 if state.is_on else 0)]
    if isinstance(state, LightState):
        return [build_channel_message(device_id, light_state_to_p44_value(state))]
    if isinstance(state, SensorState):
        return [build_sensor_message(device_id, state.numeric_value)]
    raise ValueError(f"Unsupported state type: {type(state)!r}")


def parse_incoming_message(
    message: dict[str, Any],
    kind: DeviceKind,
) -> DeviceCommand | None:
    if message.get("message") != "channel" or not message.get("tag"):
        return None

    value = float(message.get("value", 0))
    device_id = str(message["tag"])

    if kind == "switch":
        return DeviceCommand(
            device_id=device_id,
            kind="switch",
            action="turn_on" if value > 0 else "turn_off",
            raw=message,
        )
    if kind == "light":
        if value <= 0:
            return DeviceCommand(
                device_id=device_id,
                kind="light",
                action="turn_off",
                raw=message,
            )
        brightness = p44_value_to_brightness(value)
        return DeviceCommand(
            device_id=device_id,
            kind="light",
            action="set_brightness",
            value=brightness,
            raw=message,
        )
    return None


def light_state_to_p44_value(state: LightState) -> int:
    if not state.is_on:
        return 0
    if state.brightness is None:
        return P44_MAX_CHANNEL_VALUE
    scaled = round(
        (int(state.brightness) / LIGHT_MAX_BRIGHTNESS)
        * P44_MAX_CHANNEL_VALUE
    )
    return max(LIGHT_ON_THRESHOLD, min(P44_MAX_CHANNEL_VALUE, scaled))


def p44_value_to_brightness(value: int | float) -> int:
    numeric = max(0, min(P44_MAX_CHANNEL_VALUE, int(float(value))))
    if numeric == 0:
        return 0
    return max(1, round((numeric / P44_MAX_CHANNEL_VALUE) * LIGHT_MAX_BRIGHTNESS))


def _build_sensor_definition(
    spec: SupportsInitSpec | VirtualDeviceSpec,
) -> dict[str, Any]:
    sensortype, min_value, max_value, resolution = _sensor_defaults_for_unit(spec.unit)

    if spec.sensor_type is not None:
        sensortype = spec.sensor_type
    if spec.sensor_min is not None:
        min_value = spec.sensor_min
    if spec.sensor_max is not None:
        max_value = spec.sensor_max
    if spec.sensor_resolution is not None:
        resolution = spec.sensor_resolution

    sensor_def: dict[str, Any] = {
        "sensortype": sensortype,
        "usage": spec.sensor_usage,
        "hardwarename": spec.name,
        "min": min_value,
        "max": max_value,
        "resolution": resolution,
        "updateinterval": spec.sensor_update_interval or 60,
    }
    if spec.sensor_alive_sign_interval is not None:
        sensor_def["alivesigninterval"] = spec.sensor_alive_sign_interval
    return sensor_def


def _sensor_defaults_for_unit(unit: str | None) -> tuple[int, float, float, float]:
    normalized = (unit or "").strip().lower()
    if normalized in {"°c", "c", "degc"}:
        return (1, 0.0, 100.0, 0.1)
    if normalized in {"%", "percent"}:
        return (2, 0.0, 100.0, 1.0)
    if normalized in {"w", "watt", "watts"}:
        return (14, 0.0, 2300.0, 1.0)
    if normalized in {"hpa", "mbar"}:
        return (18, 0.0, 1200.0, 1.0)
    return (0, 0.0, 100.0, 1.0)


def _default_model_for_kind(kind: DeviceKind) -> str:
    if kind == "sensor":
        return "Home Assistant Virtual Sensor"
    return "Home Assistant Virtual Device"
