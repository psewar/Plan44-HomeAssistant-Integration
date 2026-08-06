"""Wire protocol for the plan44 vdcd *bridge API* (real-time push).

The bridge API (default TCP port 4444 on the bridge, the same one p44mbrd uses)
speaks the newline-delimited JSON vdc API.  Besides request/response
(``getProperty`` -> ``{"result": ...}``) it pushes ``pushNotification`` messages
for every changed property of *bridged* devices — in real time, including raw
sensor channels (e.g. acceleration) that a Matter bridge cannot represent.

A push message looks like::

    {"notification": "pushNotification", "dSUID": "30FE…1900",
     "changedproperties":
        {"sensorStates": {"acceleration": {"value": -0.46, "age": 0.002}}}}

This module is pure (no I/O, no SSH) so the parsing is fully unit-testable.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# vdc property group (wire name) -> Plan44DeviceCoordinator.data group key.
# The coordinator stores {dsuid: {"sensor": {...}, "binary_sensor": {...}}}.
_GROUP_MAP: dict[str, str] = {
    "sensorStates": "sensor",
    "binaryInputStates": "binary_sensor",
}


@dataclass(frozen=True, slots=True)
class BridgeUpdate:
    """A single pushed channel value for a device."""

    dsuid: str
    group: str  # "sensor" | "binary_sensor" (Plan44DeviceCoordinator.data group)
    key: str
    value: Any


def parse_line(raw: str) -> dict[str, Any] | None:
    """Parse one newline-delimited JSON message; None if not a JSON object."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return msg if isinstance(msg, dict) else None


def is_push(msg: Mapping[str, Any]) -> bool:
    return msg.get("notification") == "pushNotification"


def parse_push_updates(msg: Mapping[str, Any]) -> list[BridgeUpdate]:
    """Extract the sensor/binary-input channel updates from a push message.

    Returns an empty list for non-push messages, unknown property groups, or
    entries without a concrete ``value`` (so callers can pass any line through).
    """
    if not is_push(msg):
        return []
    dsuid = msg.get("dSUID")
    changed = msg.get("changedproperties")
    if not dsuid or not isinstance(changed, Mapping):
        return []

    updates: list[BridgeUpdate] = []
    for wire_group, group in _GROUP_MAP.items():
        states = changed.get(wire_group)
        if not isinstance(states, Mapping):
            continue
        for key, state in states.items():
            if isinstance(state, Mapping) and "value" in state:
                updates.append(
                    BridgeUpdate(str(dsuid), group, str(key), state["value"])
                )
    return updates
