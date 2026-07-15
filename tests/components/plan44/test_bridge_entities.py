"""Bridge diagnostic entities: connectivity binary_sensor + diagnostic sensors."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_send

from custom_components.plan44.const import DOMAIN, signal_bridge_connection


async def test_bridge_connectivity_reflects_connection(
    hass: HomeAssistant,
    config_entry: Any,
    mock_plan44_client: Any,
    entity_registry: er.EntityRegistry,
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    conn_id = entity_registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{config_entry.entry_id}_bridge_connection"
    )
    assert conn_id is not None
    state = hass.states.get(conn_id)
    assert state is not None and state.state == "on"  # mock client is connected

    # Simulate a dropped connection: the coordinator broadcasts, the entity
    # re-reads the (now False) client state.
    mock_plan44_client.is_connected = False
    async_dispatcher_send(hass, signal_bridge_connection(config_entry.entry_id))
    await hass.async_block_till_done()
    off_state = hass.states.get(conn_id)
    assert off_state is not None
    assert off_state.state == "off"


async def test_bridge_diagnostic_sensors_present(
    hass: HomeAssistant,
    config_entry: Any,
    mock_plan44_client: Any,
    entity_registry: er.EntityRegistry,
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    since_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{config_entry.entry_id}_bridge_connected_since"
    )
    reconnects_id = entity_registry.async_get_entity_id(
        "sensor", DOMAIN, f"{config_entry.entry_id}_bridge_reconnects"
    )
    assert since_id is not None
    assert reconnects_id is not None

    # connected_since is set on connect; reconnects starts at zero.
    since_state = hass.states.get(since_id)
    reconnects_state = hass.states.get(reconnects_id)
    assert since_state is not None
    assert since_state.state not in ("unknown", "unavailable")
    assert reconnects_state is not None
    assert reconnects_state.state == "0"
