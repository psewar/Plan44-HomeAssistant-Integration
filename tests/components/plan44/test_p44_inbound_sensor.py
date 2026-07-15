"""HA integration tests for the p44_device template-based import feature.

Verify that a p44_device subentry produces the right grouped entities (sensor +
binary_sensor) and that they update when plan44 pushes channel values.
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
    ATTR_PLATFORM,
    ATTR_TEMPLATE,
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
    SUBENTRY_TYPE_P44_DEVICE,
)
from custom_components.plan44.device_templates import PLATFORM_BINARY_SENSOR

_TAG = "enoceanaddress:00123456"
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


def _add_device_subentry(
    hass: HomeAssistant, data: dict[str, Any]
) -> tuple[MockConfigEntry, str]:
    entry = MockConfigEntry(
        domain=DOMAIN, title="plan44 (127.0.0.1)", data=_BASE_DATA, options={}
    )
    entry.add_to_hass(hass)
    subentry = ConfigSubentry(
        subentry_type=SUBENTRY_TYPE_P44_DEVICE,
        title=str(data.get(ATTR_NAME) or data[ATTR_P44_TAG]),
        data=MappingProxyType(data),
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    return entry, subentry.subentry_id


def _entities_for(hass: HomeAssistant, entry: MockConfigEntry) -> list[Any]:
    registry = async_get_entity_registry(hass)
    return [
        e
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id and e.config_subentry_id is not None
    ]


async def test_d2_14_41_creates_all_entities(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """The D2-14-41 template must create 7 sensors + 1 binary_sensor."""
    entry, _ = _add_device_subentry(
        hass,
        {ATTR_P44_TAG: _TAG, ATTR_TEMPLATE: "d2_14_41", ATTR_NAME: "Multi"},
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entities = _entities_for(hass, entry)
    assert len(entities) == 8
    sensors = [e for e in entities if e.domain == "sensor"]
    binary = [e for e in entities if e.domain == "binary_sensor"]
    assert len(sensors) == 7
    assert len(binary) == 1


async def test_sensor_value_updates_from_push(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """A pushed sensor value (index 4 = Acc X) must reach the sensor entity."""
    entry, _ = _add_device_subentry(
        hass,
        {ATTR_P44_TAG: _TAG, ATTR_TEMPLATE: "d2_14_41", ATTR_NAME: "Multi"},
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    await coordinator.async_handle_plan44_message(
        {"message": "sensor", "tag": _TAG, "index": 4, "value": 0.98}
    )
    await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    acc_x = next(
        e for e in registry.entities.values() if e.unique_id.endswith("acceleration_x")
    )
    state = hass.states.get(acc_x.entity_id)
    assert state is not None
    assert float(state.state) == pytest.approx(0.98, abs=1e-9)


async def test_binary_input_updates_from_push(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """A pushed input value (index 7 = contact) must reach the binary_sensor."""
    entry, _ = _add_device_subentry(
        hass,
        {ATTR_P44_TAG: _TAG, ATTR_TEMPLATE: "d2_14_41", ATTR_NAME: "Multi"},
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    await coordinator.async_handle_plan44_message(
        {"message": "input", "tag": _TAG, "index": 0, "value": 1}
    )
    await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    contact = next(
        e for e in registry.entities.values() if e.unique_id.endswith("contact")
    )
    state = hass.states.get(contact.entity_id)
    assert state is not None
    assert state.state == "on"


async def test_custom_single_sensor(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """A custom single-channel device creates exactly one entity."""
    entry, _ = _add_device_subentry(
        hass,
        {
            ATTR_P44_TAG: _TAG,
            ATTR_TEMPLATE: "custom",
            ATTR_NAME: "My Sensor",
            ATTR_P44_INDEX: 2,
        },
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entities = _entities_for(hass, entry)
    assert len(entities) == 1
    assert entities[0].domain == "sensor"


async def test_custom_binary_sensor(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """A custom binary single-channel device creates one binary_sensor."""
    entry, _ = _add_device_subentry(
        hass,
        {
            ATTR_P44_TAG: _TAG,
            ATTR_TEMPLATE: "custom",
            ATTR_NAME: "My Contact",
            ATTR_P44_INDEX: 0,
            ATTR_PLATFORM: PLATFORM_BINARY_SENSOR,
        },
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    entities = _entities_for(hass, entry)
    assert len(entities) == 1
    assert entities[0].domain == "binary_sensor"
