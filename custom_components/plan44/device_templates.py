"""Device templates for importing physical plan44 devices into Home Assistant.

A physical device registered on plan44 (e.g. an EnOcean device) exposes several
sensor/input channels.  Rather than configuring every channel by hand, the user
picks a template that describes all channels of a known device type; the
integration then creates one grouped HA device with all matching entities.

Channel layout (index + message type) mirrors plan44's own device descriptions
as read from a live bridge via the vdc API (``sensorDescriptions`` /
``binaryInputDescriptions``).  Note that plan44 numbers sensors and binary
inputs in SEPARATE 0-based sequences, which is why a sensor and an input can
both have index 0 — our dispatch keys on ``(message, tag, index)`` so they do
not collide.

plan44 already decodes telegrams and pushes ready scaled values, so HA only
needs presentation metadata (unit, device_class, state_class).
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

_MEAS = "measurement"
_TOTAL = "total_increasing"


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


def _sensor(
    index: int,
    key: str,
    name: str,
    *,
    unit: str | None = None,
    device_class: str | None = None,
    state_class: str | None = _MEAS,
) -> ChannelTemplate:
    return ChannelTemplate(
        index=index,
        key=key,
        name=name,
        platform=PLATFORM_SENSOR,
        message=MSG_SENSOR,
        unit=unit,
        device_class=device_class,
        state_class=state_class,
    )


def _input(
    index: int, key: str, name: str, device_class: str | None
) -> ChannelTemplate:
    return ChannelTemplate(
        index=index,
        key=key,
        name=name,
        platform=PLATFORM_BINARY_SENSOR,
        message=MSG_INPUT,
        device_class=device_class,
    )


# Profiles verified against a live P44-DSB-E2 bridge (vdc API getProperty).
DEVICE_TEMPLATES: dict[str, DeviceTemplate] = {
    "d2_14_41": DeviceTemplate(
        key="d2_14_41",
        label="EnOcean D2-14-41 (multisensor + acceleration)",
        channels=(
            _sensor(
                0, "temperature", "Temperature", unit="°C", device_class="temperature"
            ),
            _sensor(1, "humidity", "Humidity", unit="%", device_class="humidity"),
            _sensor(
                2, "illumination", "Illumination", unit="lx", device_class="illuminance"
            ),
            _sensor(3, "acceleration_status", "Acceleration status", state_class=None),
            _sensor(4, "acceleration_x", "Acceleration X", unit="g"),
            _sensor(5, "acceleration_y", "Acceleration Y", unit="g"),
            _sensor(6, "acceleration_z", "Acceleration Z", unit="g"),
            _input(0, "contact", "Contact", "opening"),
        ),
    ),
    "d2_14_40": DeviceTemplate(
        key="d2_14_40",
        label="EnOcean D2-14-40 (temperature, humidity, illumination)",
        channels=(
            _sensor(
                0, "temperature", "Temperature", unit="°C", device_class="temperature"
            ),
            _sensor(1, "humidity", "Humidity", unit="%", device_class="humidity"),
            _sensor(
                2, "illumination", "Illumination", unit="lx", device_class="illuminance"
            ),
        ),
    ),
    "d2_14_30": DeviceTemplate(
        key="d2_14_30",
        label="EnOcean D2-14-30 (Nexelec temperature/humidity + smoke)",
        channels=(
            _sensor(
                0, "temperature", "Temperature", unit="°C", device_class="temperature"
            ),
            _sensor(1, "humidity", "Humidity", unit="%", device_class="humidity"),
            _input(0, "smoke", "Smoke alarm", "smoke"),
            _input(1, "low_battery", "Low battery", "battery"),
        ),
    ),
    "a5_20_01": DeviceTemplate(
        key="a5_20_01",
        label="EnOcean A5-20-01 (heating valve actuator)",
        channels=(
            _sensor(
                0, "temperature", "Temperature", unit="°C", device_class="temperature"
            ),
            _input(0, "low_battery", "Low battery", "battery"),
        ),
    ),
    "a5_20_06": DeviceTemplate(
        key="a5_20_06",
        label="EnOcean A5-20-06 (Micropelt heating valve actuator)",
        channels=(
            _sensor(
                0, "temperature", "Temperature", unit="°C", device_class="temperature"
            ),
            _sensor(
                1,
                "feed_temperature",
                "Feed temperature",
                unit="°C",
                device_class="temperature",
            ),
            _sensor(2, "set_point", "Set point", state_class=None),
            _input(0, "low_battery", "Low battery", "battery"),
        ),
    ),
    "a5_10_12": DeviceTemplate(
        key="a5_10_12",
        label="EnOcean A5-10-12 (set point + temperature/humidity)",
        channels=(
            _sensor(0, "set_point", "Set point", state_class=None),
            _sensor(1, "humidity", "Humidity", unit="%", device_class="humidity"),
            _sensor(
                2, "temperature", "Temperature", unit="°C", device_class="temperature"
            ),
        ),
    ),
    "a5_07_01": DeviceTemplate(
        key="a5_07_01",
        label="EnOcean A5-07-01 (motion sensor)",
        channels=(
            _sensor(
                0, "supply_voltage", "Supply voltage", unit="V", device_class="voltage"
            ),
            _input(0, "motion", "Motion", "motion"),
        ),
    ),
    "d5_00_01": DeviceTemplate(
        key="d5_00_01",
        label="EnOcean D5-00-01 (single contact)",
        channels=(_input(0, "contact", "Contact", "opening"),),
    ),
    "smartplug_metering": DeviceTemplate(
        key="smartplug_metering",
        label="Smart plug metering (voltage/current/power/energy)",
        channels=(
            _sensor(0, "voltage", "Voltage", unit="V", device_class="voltage"),
            _sensor(1, "current", "Current", unit="A", device_class="current"),
            _sensor(2, "power", "Power", unit="W", device_class="power"),
            _sensor(
                3,
                "energy",
                "Energy",
                unit="kWh",
                device_class="energy",
                state_class=_TOTAL,
            ),
        ),
    ),
    "weather_owm": DeviceTemplate(
        key="weather_owm",
        label="Weather (OpenWeatherMap script device)",
        channels=(
            _sensor(
                0, "temperature", "Temperature", unit="°C", device_class="temperature"
            ),
            _sensor(
                1,
                "air_pressure",
                "Air pressure",
                unit="hPa",
                device_class="atmospheric_pressure",
            ),
            _sensor(2, "humidity", "Humidity", unit="%", device_class="humidity"),
            _sensor(3, "visibility", "Visibility", unit="m", device_class="distance"),
            _sensor(
                4, "wind_speed", "Wind speed", unit="m/s", device_class="wind_speed"
            ),
            _sensor(5, "wind_direction", "Wind direction", unit="°"),
            _sensor(
                6, "gust_speed", "Gust speed", unit="m/s", device_class="wind_speed"
            ),
            _sensor(
                7,
                "precipitation",
                "Precipitation",
                unit="mm",
                device_class="precipitation",
            ),
            _sensor(8, "clouds", "Clouds", unit="%"),
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
    state_class = _MEAS if platform == PLATFORM_SENSOR else None
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
