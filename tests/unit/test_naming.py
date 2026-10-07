"""Unit tests for cleaning bridge channel names into display names (no HA)."""

from __future__ import annotations

import pytest
from plan44_core.naming import display_name, display_names


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Verbatim from a live P44-DSB-E2 (vdcd 2.8.4.x).
        ("Temperature, 0.0..51.0 °C", "Temperature"),
        ("Temperature, -40.0..62.4 °C", "Temperature"),
        ("Humidity, 0.0..127.5 %", "Humidity"),
        ("Illumination, 0..131071 lx", "Illumination"),
        ("Acceleration X, -24.52..25.69 m/s2", "Acceleration X"),
        # Unitless range with the trailing space vdcd leaves behind.
        ("Acceleration Status, 0..3 ", "Acceleration Status"),
        ("Offset, -5..-1 K", "Offset"),
    ],
)
def test_range_and_unit_are_removed(raw: str, expected: str) -> None:
    assert display_name(raw) == expected


@pytest.mark.parametrize(
    "name",
    [
        "Temperature",
        "Smoke Alarm",
        "Low battery",
        # A comma that is part of the name, not a range.
        "Room, north",
        "Valve 1, upper floor",
    ],
)
def test_names_without_a_range_are_untouched(name: str) -> None:
    assert display_name(name) == name


def test_a_name_that_is_only_a_range_is_kept() -> None:
    """Stripping would leave nothing; the original is the better label."""
    assert display_name(", 0..3") == ", 0..3"


def test_cleaning_is_idempotent() -> None:
    once = display_name("Acceleration X, -24.52..25.69 m/s2")
    assert display_name(once) == once


def test_a_real_device_gets_clean_distinct_names() -> None:
    """The multisensor from the live bridge: all seven become unique and clean."""
    raw = [
        "Temperature, -40.0..62.4 °C",
        "Humidity, 0.0..127.5 %",
        "Illumination, 0..131071 lx",
        "Acceleration Status, 0..3 ",
        "Acceleration X, -24.52..25.69 m/s2",
        "Acceleration Y, -24.52..25.69 m/s2",
        "Acceleration Z, -24.52..25.69 m/s2",
    ]
    assert display_names(raw) == [
        "Temperature",
        "Humidity",
        "Illumination",
        "Acceleration Status",
        "Acceleration X",
        "Acceleration Y",
        "Acceleration Z",
    ]


def test_channels_that_differ_only_in_range_keep_their_full_names() -> None:
    """Both would become "Temperature" and be indistinguishable in the UI."""
    raw = ["Temperature, 0..50 °C", "Temperature, -40..120 °C", "Humidity, 0..100 %"]
    assert display_names(raw) == [
        "Temperature, 0..50 °C",
        "Temperature, -40..120 °C",
        "Humidity",
    ]


def test_collision_with_an_already_clean_name_is_detected() -> None:
    raw = ["Temperature", "Temperature, 0..50 °C"]
    assert display_names(raw) == ["Temperature", "Temperature, 0..50 °C"]


def test_collision_check_ignores_case() -> None:
    """Home Assistant derives entity IDs case-insensitively."""
    raw = ["Temp, 0..1 x", "temp, 0..2 y"]
    assert display_names(raw) == ["Temp, 0..1 x", "temp, 0..2 y"]


def test_no_channels() -> None:
    assert display_names([]) == []
