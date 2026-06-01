"""Tests for the single-step virtual_device subentry flow (kind from entity)."""

from __future__ import annotations

from typing import Any, cast

from homeassistant.core import HomeAssistant

from custom_components.plan44.const import SUBENTRY_TYPE_VIRTUAL_DEVICE


async def _setup(hass: HomeAssistant, config_entry: Any) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()


async def test_virtual_device_flow_derives_kind_from_entity(
    hass: HomeAssistant, config_entry: Any, mock_plan44_client: Any
) -> None:
    """The user picks only an entity; the kind is derived from its domain."""
    await _setup(hass, config_entry)
    hass.states.async_set("switch.demo", "off")

    result = cast(
        Any,
        await hass.config_entries.subentries.async_init(
            (config_entry.entry_id, SUBENTRY_TYPE_VIRTUAL_DEVICE),
            context={"source": "user"},
        ),
    )
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    # The type dropdown is gone — only the entity (+ optional fields) remain.
    assert "kind" not in result["data_schema"].schema

    result2 = cast(
        Any,
        await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {"entity_id": "switch.demo", "name": "Demo", "allow_reverse": True},
        ),
    )
    assert result2["type"] == "create_entry"
    await hass.async_block_till_done()

    subentries = [
        s
        for s in config_entry.subentries.values()
        if s.subentry_type == SUBENTRY_TYPE_VIRTUAL_DEVICE
    ]
    assert len(subentries) == 1
    assert subentries[0].data["entity_id"] == "switch.demo"
    assert subentries[0].data["kind"] == "switch"  # derived


async def test_virtual_device_flow_rejects_non_numeric_sensor(
    hass: HomeAssistant, config_entry: Any, mock_plan44_client: Any
) -> None:
    """A sensor with a non-numeric state is rejected with a clear error."""
    await _setup(hass, config_entry)
    hass.states.async_set("sensor.broken", "unavailable")

    result = cast(
        Any,
        await hass.config_entries.subentries.async_init(
            (config_entry.entry_id, SUBENTRY_TYPE_VIRTUAL_DEVICE),
            context={"source": "user"},
        ),
    )
    result2 = cast(
        Any,
        await hass.config_entries.subentries.async_configure(
            result["flow_id"],
            {"entity_id": "sensor.broken", "allow_reverse": False},
        ),
    )
    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "sensor_not_numeric"}
