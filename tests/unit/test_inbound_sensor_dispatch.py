"""Unit tests for p44_sensor coordinator dispatch and _inbound_sensor_spec.

These tests do NOT require a running Home Assistant — they create a minimal
coordinator shell via object.__new__ and mock out hass/entry as needed.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from custom_components.plan44.const import (
    ATTR_NAME,
    ATTR_P44_TAG,
    ATTR_SENSOR_MAX,
    ATTR_SENSOR_MIN,
    ATTR_SENSOR_RESOLUTION,
    ATTR_SENSOR_TYPE,
    ATTR_UNIT,
)
from custom_components.plan44.coordinator import Plan44Coordinator, _inbound_sensor_spec

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_coordinator() -> Plan44Coordinator:
    """Return a bare coordinator with only the inbound-sensor parts wired up."""
    coord = object.__new__(Plan44Coordinator)
    coord._inbound_sensor_callbacks = {}
    coord.hass = MagicMock()
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry_id"
    return coord  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# _inbound_sensor_spec
# ---------------------------------------------------------------------------


def test_spec_minimal() -> None:
    data = {ATTR_P44_TAG: "enoceanaddress:00123456"}
    spec = _inbound_sensor_spec(data)
    assert spec is not None
    assert spec.device_id == "enoceanaddress:00123456"
    assert spec.name == "enoceanaddress:00123456"
    assert spec.kind == "sensor"
    assert spec.unit is None


def test_spec_with_overrides() -> None:
    data = {
        ATTR_P44_TAG: "enoceanaddress:ABCD1234",
        ATTR_NAME: "D2-14-41 Acc X",
        ATTR_UNIT: "g",
        ATTR_SENSOR_TYPE: 5,
        ATTR_SENSOR_MIN: -2.5,
        ATTR_SENSOR_MAX: 2.615,
        ATTR_SENSOR_RESOLUTION: 0.001,
    }
    spec = _inbound_sensor_spec(data)
    assert spec is not None
    assert spec.name == "D2-14-41 Acc X"
    assert spec.unit == "g"
    assert spec.sensor_type == 5
    assert spec.sensor_min == -2.5
    assert spec.sensor_max == 2.615
    assert spec.sensor_resolution == 0.001


def test_spec_missing_tag_returns_none() -> None:
    assert _inbound_sensor_spec({}) is None
    assert _inbound_sensor_spec({ATTR_P44_TAG: ""}) is None


def test_spec_empty_unit_becomes_none() -> None:
    spec = _inbound_sensor_spec({ATTR_P44_TAG: "t", ATTR_UNIT: ""})
    assert spec is not None
    assert spec.unit is None


# ---------------------------------------------------------------------------
# Coordinator: callback registration and dispatch
# ---------------------------------------------------------------------------


_TAG = "enoceanaddress:00123456"


def test_register_and_dispatch_callback() -> None:
    coord = _make_coordinator()
    received: list[float] = []
    coord.register_inbound_sensor_callback(_TAG, 4, received.append)
    coord._dispatch_inbound_sensor(
        {"message": "sensor", "tag": _TAG, "index": 4, "value": 0.98},
        _TAG,
    )
    assert received == [0.98]


def test_dispatch_ignores_missing_value() -> None:
    coord = _make_coordinator()
    received: list[float] = []
    coord.register_inbound_sensor_callback("tag::x", 0, received.append)
    coord._dispatch_inbound_sensor({"message": "sensor", "tag": "tag::x"}, "tag::x")
    assert received == []


def test_dispatch_logs_invalid_value(caplog: pytest.LogCaptureFixture) -> None:
    coord = _make_coordinator()
    coord.register_inbound_sensor_callback("tag::x", 0, lambda v: None)
    with caplog.at_level(logging.WARNING):
        coord._dispatch_inbound_sensor(
            {"message": "sensor", "tag": "tag::x", "value": "not-a-number"},
            "tag::x",
        )
    assert any("invalid sensor value" in r.message for r in caplog.records)


def test_unregister_callback() -> None:
    coord = _make_coordinator()
    received: list[float] = []
    coord.register_inbound_sensor_callback("tag::x", 0, received.append)
    coord.unregister_inbound_sensor_callback("tag::x", 0)
    coord._dispatch_inbound_sensor(
        {"message": "sensor", "tag": "tag::x", "value": 1.0}, "tag::x"
    )
    assert received == []


def test_unregister_unknown_key_is_safe() -> None:
    coord = _make_coordinator()
    coord.unregister_inbound_sensor_callback("tag::unknown", 99)  # must not raise


def test_dispatch_uses_default_index_zero() -> None:
    coord = _make_coordinator()
    received: list[float] = []
    coord.register_inbound_sensor_callback("tag::x", 0, received.append)
    coord._dispatch_inbound_sensor(
        {"message": "sensor", "tag": "tag::x", "value": 3.14},  # no "index" key
        "tag::x",
    )
    assert received == [3.14]


def test_separate_indices_are_independent() -> None:
    coord = _make_coordinator()
    a: list[float] = []
    b: list[float] = []
    coord.register_inbound_sensor_callback("tag::x", 0, a.append)
    coord.register_inbound_sensor_callback("tag::x", 1, b.append)
    coord._dispatch_inbound_sensor(
        {"message": "sensor", "tag": "tag::x", "index": 1, "value": 9.9}, "tag::x"
    )
    assert a == []
    assert b == [9.9]


# ---------------------------------------------------------------------------
# Coordinator: passive discovery notification
# ---------------------------------------------------------------------------


def test_discovery_notification_fires_for_unknown_tag(
    caplog: pytest.LogCaptureFixture,
) -> None:
    coord = _make_coordinator()
    with (
        patch(
            "custom_components.plan44.coordinator.persistent_notification"
        ) as mock_pn_module,
        caplog.at_level(logging.INFO),
    ):
        coord._dispatch_inbound_sensor(
            {"message": "sensor", "tag": "enoceanaddress:DEADBEEF", "value": 1.23},
            "enoceanaddress:DEADBEEF",
        )
        mock_pn_module.async_create.assert_called_once()
        call_kwargs = mock_pn_module.async_create.call_args.kwargs
        assert "enoceanaddress:DEADBEEF" in call_kwargs["message"]
    assert any("Discovered new plan44 sensor" in r.message for r in caplog.records)


def test_discovery_notification_not_fired_when_callback_registered() -> None:
    coord = _make_coordinator()
    coord.register_inbound_sensor_callback("enoceanaddress:DEADBEEF", 0, lambda v: None)
    with patch(
        "custom_components.plan44.coordinator.persistent_notification"
    ) as mock_pn_module:
        coord._dispatch_inbound_sensor(
            {"message": "sensor", "tag": "enoceanaddress:DEADBEEF", "value": 1.23},
            "enoceanaddress:DEADBEEF",
        )
        mock_pn_module.async_create.assert_not_called()
