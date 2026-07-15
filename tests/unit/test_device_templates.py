"""Manual custom-import templates classify sensors for statistics correctly."""

from __future__ import annotations

from device_templates import (
    PLATFORM_BINARY_SENSOR,
    PLATFORM_SENSOR,
    build_custom_template,
)


def test_custom_energy_sensor_is_total_increasing() -> None:
    tpl = build_custom_template(
        index=0, platform=PLATFORM_SENSOR, unit="kWh", device_class="energy"
    )
    assert tpl.channels[0].state_class == "total_increasing"


def test_custom_water_sensor_is_total_increasing() -> None:
    tpl = build_custom_template(
        index=0, platform=PLATFORM_SENSOR, unit="m³", device_class="water"
    )
    assert tpl.channels[0].state_class == "total_increasing"


def test_custom_plain_sensor_is_measurement() -> None:
    tpl = build_custom_template(
        index=0, platform=PLATFORM_SENSOR, unit="°C", device_class="temperature"
    )
    assert tpl.channels[0].state_class == "measurement"


def test_custom_sensor_without_device_class_is_measurement() -> None:
    tpl = build_custom_template(
        index=2, platform=PLATFORM_SENSOR, unit=None, device_class=None
    )
    assert tpl.channels[0].state_class == "measurement"


def test_custom_binary_sensor_has_no_state_class() -> None:
    tpl = build_custom_template(
        index=0, platform=PLATFORM_BINARY_SENSOR, unit=None, device_class="motion"
    )
    assert tpl.channels[0].state_class is None
