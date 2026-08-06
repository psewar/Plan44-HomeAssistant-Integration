"""Unit tests for the plan44 bridge-API wire protocol parser (no HA/SSH)."""

from __future__ import annotations

from custom_components.plan44.bridge_protocol import (
    BridgeUpdate,
    is_push,
    parse_line,
    parse_push_updates,
)

_DSUID = "00112233445566778899AABBCCDDEEFF00"  # placeholder, not a real device

# A real message captured from the bridge API over the SSH tunnel.
_ACCEL_PUSH = (
    '{"changedproperties":{"sensorStates":{"acceleration":'
    '{"error":0,"value":-0.46724560856819153,"age":0.0025}}},'
    '"dSUID":"' + _DSUID + '","notification":"pushNotification"}'
)


def test_parse_line_valid_object() -> None:
    msg = parse_line(_ACCEL_PUSH)
    assert isinstance(msg, dict)
    assert msg["notification"] == "pushNotification"


def test_parse_line_rejects_junk() -> None:
    assert parse_line("") is None
    assert parse_line("   ") is None
    assert parse_line("not json") is None
    assert parse_line("[1,2,3]") is None  # array, not an object


def test_parse_push_updates_single_sensor() -> None:
    msg = parse_line(_ACCEL_PUSH)
    assert msg is not None
    updates = parse_push_updates(msg)
    assert updates == [
        BridgeUpdate(_DSUID, "sensor", "acceleration", -0.46724560856819153)
    ]


def test_parse_push_updates_multiple_and_binary() -> None:
    msg = {
        "notification": "pushNotification",
        "dSUID": _DSUID,
        "changedproperties": {
            "sensorStates": {
                "acceleration": {"value": 1.0, "age": 0.0},
                "temperature": {"value": 21.5, "age": 3.0},
            },
            "binaryInputStates": {"generic": {"value": False, "age": 0.1}},
        },
    }
    updates = parse_push_updates(msg)
    assert BridgeUpdate(_DSUID, "sensor", "acceleration", 1.0) in updates
    assert BridgeUpdate(_DSUID, "sensor", "temperature", 21.5) in updates
    assert BridgeUpdate(_DSUID, "binary_sensor", "generic", False) in updates
    assert len(updates) == 3


def test_getproperty_result_is_not_a_push() -> None:
    msg = parse_line('{"result":{"model":"P44-DSB-E2","name":""}}')
    assert msg is not None
    assert not is_push(msg)
    assert parse_push_updates(msg) == []


def test_push_without_dsuid_or_changes_is_ignored() -> None:
    assert parse_push_updates({"notification": "pushNotification"}) == []
    assert (
        parse_push_updates(
            {
                "notification": "pushNotification",
                "dSUID": _DSUID,
                "changedproperties": 5,
            }
        )
        == []
    )


def test_state_without_value_is_skipped() -> None:
    msg = {
        "notification": "pushNotification",
        "dSUID": _DSUID,
        "changedproperties": {"sensorStates": {"temperature": {"age": 3.0}}},
    }
    assert parse_push_updates(msg) == []
