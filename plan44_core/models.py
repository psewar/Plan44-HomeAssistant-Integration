from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

DeviceKind = Literal["switch", "light", "sensor", "binary_sensor"]


@dataclass(slots=True)
class VirtualDeviceSpec:
    device_id: str
    name: str
    kind: DeviceKind
    allow_reverse: bool = True
    room_hint: str | None = None
    unit: str | None = None
    model: str | None = None
    iconname: str = "vdc_ext"
    sync: bool = True
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def tag(self) -> str:
        return self.device_id


@dataclass(slots=True)
class DeviceState:
    pass


@dataclass(slots=True)
class SwitchState(DeviceState):
    is_on: bool


@dataclass(slots=True)
class BinarySensorState(DeviceState):
    is_on: bool


@dataclass(slots=True)
class LightState(DeviceState):
    is_on: bool
    brightness: int | None = None


@dataclass(slots=True)
class SensorState(DeviceState):
    numeric_value: float


@dataclass(slots=True)
class DeviceCommand:
    device_id: str
    kind: DeviceKind
    action: Literal["turn_on", "turn_off", "set_brightness"]
    value: int | float | None = None
    raw: dict | None = None
