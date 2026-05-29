"""HA integration tests for the p44_sensor feature.

These tests require a running Home Assistant (via the HA test harness) and
verify that p44_sensor subentries produce real sensor entities that update
their state when the coordinator dispatches inbound sensor values.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any

import pytest
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.plan44.const import (
    ATTR_NAME,
    ATTR_P44_INDEX,
    ATTR_P44_TAG,
    ATTR_UNIT,
    CONF_AUTO_REPUBLISH,
    CONF_BLOCKLIST_ENTITY_ID_PREFIXES,
    CONF_BLOCKLIST_INTEGRATIONS,
    CONF_HOST,
    CONF_PORT,
    CONF_RECONNECT_INTERVAL,
    CONF_REVERSE_ENABLED,
    CONF_VDC_MODEL_NAME,
    DEFAULT_AUTO_REPUBLISH,
    DEFAULT_BLOCKLIST_ENTITY_ID_PREFIXES,
    DEFAULT_BLOCKLIST_INTEGRATIONS,
    DEFAULT_RECONNECT_INTERVAL,
    DEFAULT_REVERSE_ENABLED,
    DEFAULT_VDC_MODEL_NAME,
    DOMAIN,
    SUBENTRY_TYPE_P44_SENSOR,
)

_BASE_DATA = {
    CONF_HOST: "127.0.0.1",
    CONF_PORT: 8999,
    CONF_VDC_MODEL_NAME: DEFAULT_VDC_MODEL_NAME,
    CONF_AUTO_REPUBLISH: DEFAULT_AUTO_REPUBLISH,
    CONF_REVERSE_ENABLED: DEFAULT_REVERSE_ENABLED,
    CONF_RECONNECT_INTERVAL: DEFAULT_RECONNECT_INTERVAL,
    CONF_BLOCKLIST_INTEGRATIONS: DEFAULT_BLOCKLIST_INTEGRATIONS,
    CONF_BLOCKLIST_ENTITY_ID_PREFIXES: DEFAULT_BLOCKLIST_ENTITY_ID_PREFIXES,
}


def _make_entry_with_p44_sensor_subentry(
    hass: HomeAssistant,
    *,
    tag: str = "enoceanaddress:00123456",
    index: int = 4,
    name: str = "Acc X",
    unit: str = "g",
) -> tuple[MockConfigEntry, str]:
    """Create a MockConfigEntry with one p44_sensor subentry pre-installed.

    Returns (entry, subentry_id).
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="plan44 (127.0.0.1)",
        data=_BASE_DATA,
        options={},
    )
    entry.add_to_hass(hass)

    subentry = ConfigSubentry(
        subentry_type=SUBENTRY_TYPE_P44_SENSOR,
        title=name,
        data=MappingProxyType(
            {
                ATTR_P44_TAG: tag,
                ATTR_P44_INDEX: index,
                ATTR_NAME: name,
                ATTR_UNIT: unit,
            }
        ),
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    return entry, subentry.subentry_id


async def test_sensor_entity_created_from_p44_sensor_subentry(
    hass: HomeAssistant,
    mock_plan44_client: Any,
) -> None:
    """A p44_sensor subentry must produce a sensor entity in the HA registry."""
    entry, subentry_id = _make_entry_with_p44_sensor_subentry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    entities = [
        e for e in registry.entities.values() if e.config_entry_id == entry.entry_id
    ]
    assert len(entities) == 1
    entity = entities[0]
    assert "sensor" in entity.entity_id
    assert entity.unique_id == f"{entry.entry_id}_{subentry_id}"


async def test_sensor_entity_value_updates_from_coordinator(
    hass: HomeAssistant,
    mock_plan44_client: Any,
) -> None:
    """Sensor state must update when coordinator dispatches an inbound push."""
    entry, _ = _make_entry_with_p44_sensor_subentry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator

    await coordinator.async_handle_plan44_message(
        {
            "message": "sensor",
            "tag": "enoceanaddress:00123456",
            "index": 4,
            "value": 0.98,
        }
    )
    await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    entities = [
        e for e in registry.entities.values() if e.config_entry_id == entry.entry_id
    ]
    state = hass.states.get(entities[0].entity_id)
    assert state is not None
    assert float(state.state) == pytest.approx(0.98, abs=1e-9)
    assert state.attributes.get("unit_of_measurement") == "g"


async def test_inbound_sensor_only_updates_matching_index(
    hass: HomeAssistant,
    mock_plan44_client: Any,
) -> None:
    """A push for index 3 must not update a sensor registered for index 4."""
    entry, _ = _make_entry_with_p44_sensor_subentry(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator

    # Push for a DIFFERENT index — the index-4 sensor must not be updated
    await coordinator.async_handle_plan44_message(
        {
            "message": "sensor",
            "tag": "enoceanaddress:00123456",
            "index": 3,
            "value": 99.0,
        }
    )
    await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    entities = [
        e for e in registry.entities.values() if e.config_entry_id == entry.entry_id
    ]
    state = hass.states.get(entities[0].entity_id)
    assert state is not None
    assert state.state == "unknown"  # never received a push for index 4
