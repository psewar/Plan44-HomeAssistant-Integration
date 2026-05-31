"""HA integration tests for REST-discovered (dSUID-based) p44_device import."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.plan44.const import (
    ATTR_CHANNELS,
    ATTR_DSUID,
    ATTR_MODEL,
    ATTR_NAME,
    CONF_AUTO_REPUBLISH,
    CONF_BLOCKLIST_ENTITY_ID_PREFIXES,
    CONF_BLOCKLIST_INTEGRATIONS,
    CONF_HOST,
    CONF_PORT,
    CONF_RECONNECT_INTERVAL,
    CONF_REVERSE_ENABLED,
    CONF_VDC_MODEL_NAME,
    CONF_WEB_PASSWORD,
    CONF_WEB_URL,
    CONF_WEB_USER,
    DEFAULT_AUTO_REPUBLISH,
    DEFAULT_BLOCKLIST_ENTITY_ID_PREFIXES,
    DEFAULT_BLOCKLIST_INTEGRATIONS,
    DEFAULT_RECONNECT_INTERVAL,
    DEFAULT_REVERSE_ENABLED,
    DEFAULT_VDC_MODEL_NAME,
    DOMAIN,
    SUBENTRY_TYPE_P44_DEVICE,
)

_DSUID = "C153DD0BD8F15C0EC0731588056C0C7B00"
_DATA = {
    CONF_HOST: "127.0.0.1",
    CONF_PORT: 8999,
    CONF_VDC_MODEL_NAME: DEFAULT_VDC_MODEL_NAME,
    CONF_AUTO_REPUBLISH: DEFAULT_AUTO_REPUBLISH,
    CONF_REVERSE_ENABLED: DEFAULT_REVERSE_ENABLED,
    CONF_RECONNECT_INTERVAL: DEFAULT_RECONNECT_INTERVAL,
    CONF_BLOCKLIST_INTEGRATIONS: DEFAULT_BLOCKLIST_INTEGRATIONS,
    CONF_BLOCKLIST_ENTITY_ID_PREFIXES: DEFAULT_BLOCKLIST_ENTITY_ID_PREFIXES,
    CONF_WEB_URL: "https://bridge.example",
    CONF_WEB_USER: "user",
    CONF_WEB_PASSWORD: "secret",
}

_CHANNELS = [
    {
        "key": "temperature",
        "name": "Temperature",
        "platform": "sensor",
        "unit": "°C",
        "device_class": "temperature",
        "state_class": "measurement",
    },
    {
        "key": "low_battery",
        "name": "Low battery",
        "platform": "binary_sensor",
        "unit": None,
        "device_class": "battery",
        "state_class": None,
    },
]

_STATES = {
    _DSUID: {
        "sensor": {"temperature": 21.5},
        "binary_sensor": {"low_battery": False},
    }
}


def _make_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="plan44", data=_DATA, options={})
    entry.add_to_hass(hass)
    subentry = ConfigSubentry(
        subentry_type=SUBENTRY_TYPE_P44_DEVICE,
        title="Valve",
        data=MappingProxyType(
            {
                ATTR_DSUID: _DSUID,
                ATTR_NAME: "Valve",
                ATTR_MODEL: "Micropelt (A5-20-06)",
                ATTR_CHANNELS: _CHANNELS,
            }
        ),
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    return entry


async def test_rest_device_creates_polled_entities(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    entry = _make_entry(hass)
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_states",
        new=AsyncMock(return_value=_STATES),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    entities = [
        e for e in registry.entities.values() if e.config_entry_id == entry.entry_id
    ]
    assert len(entities) == 2
    domains = {e.domain for e in entities}
    assert domains == {"sensor", "binary_sensor"}


async def test_rest_device_values_reflect_poll(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    entry = _make_entry(hass)
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_states",
        new=AsyncMock(return_value=_STATES),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    by_uid = {e.unique_id: e for e in registry.entities.values()}
    temp = by_uid[f"{entry.entry_id}_{next(iter(entry.subentries))}_temperature"]
    bat = by_uid[f"{entry.entry_id}_{next(iter(entry.subentries))}_low_battery"]

    temp_state = hass.states.get(temp.entity_id)
    assert temp_state is not None
    assert float(temp_state.state) == 21.5
    assert temp_state.attributes.get("unit_of_measurement") == "°C"

    bat_state = hass.states.get(bat.entity_id)
    assert bat_state is not None
    assert bat_state.state == "off"  # low_battery False


async def test_rest_device_unavailable_without_web_api_data(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """If polling returns no data for the dSUID, the sensor reports unavailable."""
    entry = _make_entry(hass)
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_states",
        new=AsyncMock(return_value={}),  # no states for our dSUID
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    temp = next(
        e for e in registry.entities.values() if e.unique_id.endswith("_temperature")
    )
    state = hass.states.get(temp.entity_id)
    assert state is not None
    assert state.state == "unavailable"
