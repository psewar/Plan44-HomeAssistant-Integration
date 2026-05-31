"""Unit tests for inbound (P44 -> HA) dispatch, templates and the resolver.

These tests do NOT require a running Home Assistant — they create a minimal
coordinator shell via object.__new__ and mock out hass/entry as needed.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from custom_components.plan44.const import (
    ATTR_DEVICE_CLASS,
    ATTR_NAME,
    ATTR_P44_INDEX,
    ATTR_P44_TAG,
    ATTR_PLATFORM,
    ATTR_TEMPLATE,
)
from custom_components.plan44.coordinator import Plan44Coordinator
from custom_components.plan44.device_templates import (
    DEVICE_TEMPLATES,
    MSG_INPUT,
    MSG_SENSOR,
    PLATFORM_BINARY_SENSOR,
    PLATFORM_SENSOR,
    TEMPLATE_CUSTOM,
    build_custom_template,
    get_template,
    template_options,
)
from custom_components.plan44.inbound import resolve_device

_TAG = "enoceanaddress:00123456"


def _make_coordinator() -> Plan44Coordinator:
    coord = object.__new__(Plan44Coordinator)
    coord._inbound_callbacks = {}  # type: ignore[attr-defined]
    coord._discovered_indices_by_tag = {}  # type: ignore[attr-defined]
    coord.hass = MagicMock()
    coord.entry = MagicMock()
    coord.entry.entry_id = "test_entry_id"
    return coord  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# device_templates
# ---------------------------------------------------------------------------


def test_d2_14_41_has_all_channels() -> None:
    tpl = get_template("d2_14_41")
    assert tpl is not None
    assert len(tpl.channels) == 8
    by_key = {c.key: c for c in tpl.channels}
    assert by_key["temperature"].device_class == "temperature"
    assert by_key["acceleration_x"].name == "Acceleration X"
    assert by_key["acceleration_x"].unit == "g"
    # contact is a binary input with its own 0-based index sequence
    assert by_key["contact"].platform == PLATFORM_BINARY_SENSOR
    assert by_key["contact"].message == MSG_INPUT
    assert by_key["contact"].index == 0


def test_template_options_includes_custom() -> None:
    options = template_options()
    assert TEMPLATE_CUSTOM in options
    assert "d2_14_41" in options


def test_build_custom_template_sensor() -> None:
    tpl = build_custom_template(
        index=3, platform=PLATFORM_SENSOR, unit="W", device_class="power"
    )
    (channel,) = tpl.channels
    assert channel.index == 3
    assert channel.message == MSG_SENSOR
    assert channel.name is None  # adopts device name
    assert channel.unit == "W"


def test_build_custom_template_binary() -> None:
    tpl = build_custom_template(
        index=0, platform=PLATFORM_BINARY_SENSOR, unit=None, device_class="motion"
    )
    (channel,) = tpl.channels
    assert channel.message == MSG_INPUT
    assert channel.state_class is None


def test_all_templates_have_unique_message_index() -> None:
    for key, tpl in DEVICE_TEMPLATES.items():
        pairs = [(c.message, c.index) for c in tpl.channels]
        assert len(pairs) == len(set(pairs)), f"duplicate (message,index) in {key}"
        keys = [c.key for c in tpl.channels]
        assert len(keys) == len(set(keys)), f"duplicate key in {key}"


# ---------------------------------------------------------------------------
# inbound.resolve_device
# ---------------------------------------------------------------------------


def test_resolve_template_device() -> None:
    resolved = resolve_device(
        {ATTR_P44_TAG: _TAG, ATTR_TEMPLATE: "d2_14_41", ATTR_NAME: "Multi"}
    )
    assert resolved is not None
    tag, name, channels = resolved
    assert tag == _TAG
    assert name == "Multi"
    assert len(channels) == 8


def test_resolve_custom_device() -> None:
    resolved = resolve_device(
        {
            ATTR_P44_TAG: _TAG,
            ATTR_TEMPLATE: TEMPLATE_CUSTOM,
            ATTR_NAME: "Door",
            ATTR_P44_INDEX: 7,
            ATTR_PLATFORM: PLATFORM_BINARY_SENSOR,
            ATTR_DEVICE_CLASS: "opening",
        }
    )
    assert resolved is not None
    _, name, channels = resolved
    assert name == "Door"
    assert len(channels) == 1
    assert channels[0].index == 7
    assert channels[0].platform == PLATFORM_BINARY_SENSOR


def test_resolve_missing_tag_returns_none() -> None:
    assert resolve_device({ATTR_TEMPLATE: "d2_14_41"}) is None


def test_resolve_unknown_template_yields_no_channels() -> None:
    resolved = resolve_device({ATTR_P44_TAG: _TAG, ATTR_TEMPLATE: "nope"})
    assert resolved is not None
    _, _, channels = resolved
    assert channels == ()


def test_resolve_name_defaults_to_tag() -> None:
    resolved = resolve_device({ATTR_P44_TAG: _TAG, ATTR_TEMPLATE: "d2_14_40"})
    assert resolved is not None
    _, name, _ = resolved
    assert name == _TAG


# ---------------------------------------------------------------------------
# Coordinator dispatch
# ---------------------------------------------------------------------------


def test_register_and_dispatch_sensor() -> None:
    coord = _make_coordinator()
    received: list[float] = []
    coord.register_inbound_callback(MSG_SENSOR, _TAG, 4, received.append)
    coord.dispatch_inbound_channel(
        {"message": "sensor", "tag": _TAG, "index": 4, "value": 0.98}, _TAG
    )
    assert received == [0.98]


def test_register_and_dispatch_input() -> None:
    coord = _make_coordinator()
    received: list[float] = []
    coord.register_inbound_callback(MSG_INPUT, _TAG, 7, received.append)
    coord.dispatch_inbound_channel(
        {"message": "input", "tag": _TAG, "index": 7, "value": 1}, _TAG
    )
    assert received == [1.0]


def test_sensor_and_input_same_index_are_independent() -> None:
    coord = _make_coordinator()
    s: list[float] = []
    i: list[float] = []
    coord.register_inbound_callback(MSG_SENSOR, _TAG, 0, s.append)
    coord.register_inbound_callback(MSG_INPUT, _TAG, 0, i.append)
    coord.dispatch_inbound_channel(
        {"message": "input", "tag": _TAG, "index": 0, "value": 1}, _TAG
    )
    assert s == []
    assert i == [1.0]


def test_dispatch_ignores_missing_value() -> None:
    coord = _make_coordinator()
    received: list[float] = []
    coord.register_inbound_callback(MSG_SENSOR, _TAG, 0, received.append)
    coord.dispatch_inbound_channel({"message": "sensor", "tag": _TAG}, _TAG)
    assert received == []


def test_dispatch_logs_invalid_value(caplog: pytest.LogCaptureFixture) -> None:
    coord = _make_coordinator()
    coord.register_inbound_callback(MSG_SENSOR, _TAG, 0, lambda v: None)
    with caplog.at_level(logging.WARNING):
        coord.dispatch_inbound_channel(
            {"message": "sensor", "tag": _TAG, "value": "nan-ish"}, _TAG
        )
    assert any("invalid sensor value" in r.message for r in caplog.records)


def test_unregister_callback() -> None:
    coord = _make_coordinator()
    received: list[float] = []
    coord.register_inbound_callback(MSG_SENSOR, _TAG, 0, received.append)
    coord.unregister_inbound_callback(MSG_SENSOR, _TAG, 0)
    coord.dispatch_inbound_channel(
        {"message": "sensor", "tag": _TAG, "value": 1.0}, _TAG
    )
    assert received == []


def test_unregister_unknown_key_is_safe() -> None:
    coord = _make_coordinator()
    coord.unregister_inbound_callback(MSG_SENSOR, _TAG, 99)


def test_dispatch_default_index_zero() -> None:
    coord = _make_coordinator()
    received: list[float] = []
    coord.register_inbound_callback(MSG_SENSOR, _TAG, 0, received.append)
    coord.dispatch_inbound_channel(
        {"message": "sensor", "tag": _TAG, "value": 3.14}, _TAG
    )
    assert received == [3.14]


# ---------------------------------------------------------------------------
# Discovery notification
# ---------------------------------------------------------------------------


def test_discovery_notification_fires_for_unknown_tag(
    caplog: pytest.LogCaptureFixture,
) -> None:
    coord = _make_coordinator()
    with (
        patch(
            "custom_components.plan44.coordinator.persistent_notification"
        ) as mock_pn,
        caplog.at_level(logging.INFO),
    ):
        coord.dispatch_inbound_channel(
            {
                "message": "sensor",
                "tag": "enoceanaddress:DEAD",
                "index": 4,
                "value": 1.2,
            },
            "enoceanaddress:DEAD",
        )
        mock_pn.async_create.assert_called_once()
        msg = mock_pn.async_create.call_args.kwargs["message"]
        assert "enoceanaddress:DEAD" in msg
    assert any(
        "Discovered unimported plan44 device" in r.message for r in caplog.records
    )


def test_discovery_notification_accumulates_indices() -> None:
    coord = _make_coordinator()
    tag = "enoceanaddress:DEAD"
    with patch(
        "custom_components.plan44.coordinator.persistent_notification"
    ) as mock_pn:
        coord.dispatch_inbound_channel(
            {"message": "sensor", "tag": tag, "index": 0, "value": 1.0}, tag
        )
        coord.dispatch_inbound_channel(
            {"message": "sensor", "tag": tag, "index": 4, "value": 2.0}, tag
        )
        # second notification lists both indices
        last_msg = mock_pn.async_create.call_args.kwargs["message"]
        assert "0, 4" in last_msg


def test_discovery_not_fired_when_callback_registered() -> None:
    coord = _make_coordinator()
    coord.register_inbound_callback(MSG_SENSOR, _TAG, 0, lambda v: None)
    with patch(
        "custom_components.plan44.coordinator.persistent_notification"
    ) as mock_pn:
        coord.dispatch_inbound_channel(
            {"message": "sensor", "tag": _TAG, "index": 0, "value": 1.2}, _TAG
        )
        mock_pn.async_create.assert_not_called()
