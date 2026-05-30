"""Device templates for importing physical plan44 devices into Home Assistant.

A physical device registered on plan44 (e.g. an EnOcean multisensor) exposes
several sensor/input channels.  Rather than configuring every channel by hand,
the user picks a template that describes all channels of a known device type;
the integration then creates one grouped HA device with all matching entities.

The channel tables mirror plan44-vdcd's EnOcean profile definitions
(enoceanvld.cpp).  plan44 already decodes the raw telegram and pushes ready
scaled values, so HA only needs the presentation metadata (name, unit,
device_class) — not the raw min/max/resolution.
"""

from __future__ import annotations

from dataclasses import dataclass

# HA platforms a channel can map to
PLATFORM_SENSOR = "sensor"
PLATFORM_BINARY_SENSOR = "binary_sensor"

# plan44 inbound message types that carry a channel value
MSG_SENSOR = "sensor"
MSG_INPUT = "input"

# Template key for the manual single-channel fallback
TEMPLATE_CUSTOM = "custom"

_MEASUREMENT = "measurement"


@dataclass(frozen=True, slots=True)
class ChannelTemplate:
    """One channel of a device template → one HA entity."""

    index: int
    key: str  # stable id used in unique_id and entity name suffix
    name: str | None  # channel name; None → entity adopts the device name
    platform: str  # PLATFORM_SENSOR | PLATFORM_BINARY_SENSOR
    message: str  # MSG_SENSOR | MSG_INPUT (which P44 message carries it)
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None


@dataclass(frozen=True, slots=True)
class DeviceTemplate:
    """A named device profile describing all of its channels."""

    key: str
    label: str
    channels: tuple[ChannelTemplate, ...]


# Confirmed against plan44-vdcd enoceanvld.cpp (D2-14-41 lines 176-185,
# D2-14-40 lines 172-175). Acceleration has no HA device_class; unit is "g".
DEVICE_TEMPLATES: dict[str, DeviceTemplate] = {
    "d2_14_41": DeviceTemplate(
        key="d2_14_41",
        label="EnOcean D2-14-41 (multisensor + acceleration)",
        channels=(
            ChannelTemplate(
                0,
                "temperature",
                "Temperature",
                PLATFORM_SENSOR,
                MSG_SENSOR,
                "°C",
                "temperature",
                _MEASUREMENT,
            ),
            ChannelTemplate(
                1,
                "humidity",
                "Humidity",
                PLATFORM_SENSOR,
                MSG_SENSOR,
                "%",
                "humidity",
                _MEASUREMENT,
            ),
            ChannelTemplate(
                2,
                "illumination",
                "Illumination",
                PLATFORM_SENSOR,
                MSG_SENSOR,
                "lx",
                "illuminance",
                _MEASUREMENT,
            ),
            ChannelTemplate(
                3,
                "acceleration_status",
                "Acceleration status",
                PLATFORM_SENSOR,
                MSG_SENSOR,
                None,
                None,
                None,
            ),
            ChannelTemplate(
                4,
                "acceleration_x",
                "Acceleration X",
                PLATFORM_SENSOR,
                MSG_SENSOR,
                "g",
                None,
                _MEASUREMENT,
            ),
            ChannelTemplate(
                5,
                "acceleration_y",
                "Acceleration Y",
                PLATFORM_SENSOR,
                MSG_SENSOR,
                "g",
                None,
                _MEASUREMENT,
            ),
            ChannelTemplate(
                6,
                "acceleration_z",
                "Acceleration Z",
                PLATFORM_SENSOR,
                MSG_SENSOR,
                "g",
                None,
                _MEASUREMENT,
            ),
            ChannelTemplate(
                7,
                "contact",
                "Contact",
                PLATFORM_BINARY_SENSOR,
                MSG_INPUT,
                None,
                "opening",
                None,
            ),
        ),
    ),
    "d2_14_40": DeviceTemplate(
        key="d2_14_40",
        label="EnOcean D2-14-40 (temperature, humidity, illumination)",
        channels=(
            ChannelTemplate(
                0,
                "temperature",
                "Temperature",
                PLATFORM_SENSOR,
                MSG_SENSOR,
                "°C",
                "temperature",
                _MEASUREMENT,
            ),
            ChannelTemplate(
                1,
                "humidity",
                "Humidity",
                PLATFORM_SENSOR,
                MSG_SENSOR,
                "%",
                "humidity",
                _MEASUREMENT,
            ),
            ChannelTemplate(
                2,
                "illumination",
                "Illumination",
                PLATFORM_SENSOR,
                MSG_SENSOR,
                "lx",
                "illuminance",
                _MEASUREMENT,
            ),
        ),
    ),
}


def template_options() -> dict[str, str]:
    """Return {template_key: label} for all selectable templates (incl. custom)."""
    options = {key: tpl.label for key, tpl in DEVICE_TEMPLATES.items()}
    options[TEMPLATE_CUSTOM] = "Single sensor (manual)"
    return options


def get_template(key: str) -> DeviceTemplate | None:
    return DEVICE_TEMPLATES.get(key)


def build_custom_template(
    *,
    index: int,
    platform: str,
    unit: str | None,
    device_class: str | None,
) -> DeviceTemplate:
    """Build a one-channel template for the manual import case.

    The single channel has no name (None) so the entity adopts the device
    name the user gave the subentry.
    """
    message = MSG_INPUT if platform == PLATFORM_BINARY_SENSOR else MSG_SENSOR
    state_class = _MEASUREMENT if platform == PLATFORM_SENSOR else None
    return DeviceTemplate(
        key=TEMPLATE_CUSTOM,
        label="Single sensor (manual)",
        channels=(
            ChannelTemplate(
                index=index,
                key="value",
                name=None,
                platform=platform,
                message=message,
                unit=unit,
                device_class=device_class,
                state_class=state_class,
            ),
        ),
    )
