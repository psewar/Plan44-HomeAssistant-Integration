"""HA integration tests for REST-discovered (dSUID-based) p44_device import."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, cast
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.plan44.const import (
    ATTR_CHANNELS,
    ATTR_COLOR_TEMP_MAX_MIRED,
    ATTR_COLOR_TEMP_MIN_MIRED,
    ATTR_DSUID,
    ATTR_HAS_COLOR_TEMP,
    ATTR_HAS_HS_COLOR,
    ATTR_HAS_XY_COLOR,
    ATTR_MODEL,
    ATTR_NAME,
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
    CONF_WEB_PASSWORD,
    CONF_WEB_USER,
    DEFAULT_AUTO_REPUBLISH,
    DEFAULT_BLOCKLIST_ENTITY_ID_PREFIXES,
    DEFAULT_BLOCKLIST_INTEGRATIONS,
    DEFAULT_RECONNECT_INTERVAL,
    DEFAULT_REVERSE_ENABLED,
    DEFAULT_VDC_MODEL_NAME,
    DOMAIN,
    ISSUE_WEB_API_UNREACHABLE,
    KIND_LIGHT,
    SUBENTRY_TYPE_P44_DEVICE,
)
from custom_components.plan44.web_client import LightChannelState, Plan44WebApiError

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
    # No web_url — it is derived from the host (https://127.0.0.1).
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
        e
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id and e.config_subentry_id is not None
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


async def test_web_api_url_derived_from_host(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """The web API URL is derived from the host (no separate URL field).

    _DATA has no web_url, only host=127.0.0.1, so successful setup proves the
    URL was derived as https://127.0.0.1.
    """
    entry = _make_entry(hass)
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_states",
        new=AsyncMock(return_value=_STATES),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    web_api = entry.runtime_data.web_api
    assert web_api is not None
    assert web_api.base_url == "https://127.0.0.1"


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


async def test_rest_device_entities_linked_to_subentry(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """Imported entities attach to their sub-entry, not the orphan bucket.

    They are added with ``config_subentry_id`` so the device shows under its
    "Plan44 device" sub-entry instead of "devices that don't belong to a
    sub-entry".
    """
    entry = _make_entry(hass)
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_states",
        new=AsyncMock(return_value=_STATES),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    subentry_id = next(iter(entry.subentries))
    registry = async_get_entity_registry(hass)
    ents = [
        e
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id and e.config_subentry_id is not None
    ]
    assert len(ents) == 2  # temperature + low_battery
    assert all(e.config_subentry_id == subentry_id for e in ents)


async def test_web_api_unreachable_creates_and_clears_repair_issue(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """A failing web-API poll raises a repair issue that clears on recovery."""
    entry = _make_entry(hass)
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_states",
        new=AsyncMock(side_effect=Plan44WebApiError("boom")),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    issue_registry = ir.async_get(hass)
    assert issue_registry.async_get_issue(DOMAIN, ISSUE_WEB_API_UNREACHABLE) is not None

    # A subsequent successful poll clears the issue.
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_states",
        new=AsyncMock(return_value=_STATES),
    ):
        device_coordinator = entry.runtime_data.device_coordinator
        assert device_coordinator is not None
        await device_coordinator.async_refresh()
        await hass.async_block_till_done()

    assert issue_registry.async_get_issue(DOMAIN, ISSUE_WEB_API_UNREACHABLE) is None


async def test_rest_device_reconfigure_is_name_only(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """Editing a picker-imported (dSUID) device offers only the display name.

    The tag/profile fields of the manual import form must not appear, and
    saving must not inject a stray p44_tag/template into the dSUID subentry.
    """
    entry = _make_entry(hass)
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_states",
        new=AsyncMock(return_value=_STATES),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        subentry_id = next(iter(entry.subentries))
        result = cast(
            Any,
            await hass.config_entries.subentries.async_init(
                (entry.entry_id, SUBENTRY_TYPE_P44_DEVICE),
                context={"source": "reconfigure", "subentry_id": subentry_id},
            ),
        )
        assert result["type"] == "form"
        assert result["step_id"] == "reconfigure"
        keys = {str(k) for k in result["data_schema"].schema}
        assert ATTR_NAME in keys
        assert ATTR_P44_TAG not in keys  # the leftover field is gone
        assert ATTR_TEMPLATE not in keys

        result2 = cast(
            Any,
            await hass.config_entries.subentries.async_configure(
                result["flow_id"], {ATTR_NAME: "Heizventil Büro"}
            ),
        )
        assert result2["type"] == "abort"
        assert result2["reason"] == "reconfigure_successful"
        await hass.async_block_till_done()

    data = entry.subentries[subentry_id].data
    assert data[ATTR_NAME] == "Heizventil Büro"
    assert data[ATTR_DSUID] == _DSUID  # identity preserved
    assert data[ATTR_CHANNELS] == _CHANNELS  # channels preserved
    assert ATTR_P44_TAG not in data  # no leftover tag injected
    assert ATTR_TEMPLATE not in data


# ---------------------------------------------------------------------------
# Light (output) device tests
# ---------------------------------------------------------------------------

_LIGHT_DSUID = "FABCDE0102030405060708090A0B0C0D0E"
_LIGHT_SUBENTRY_DATA = MappingProxyType(
    {
        ATTR_DSUID: _LIGHT_DSUID,
        ATTR_NAME: "HueIris Kay",
        ATTR_MODEL: "Extended color light",
        ATTR_PLATFORM: KIND_LIGHT,
        ATTR_HAS_COLOR_TEMP: True,
        ATTR_COLOR_TEMP_MIN_MIRED: 153.0,
        ATTR_COLOR_TEMP_MAX_MIRED: 500.0,
        ATTR_HAS_HS_COLOR: True,
        ATTR_HAS_XY_COLOR: True,
    }
)
_LIGHT_STATES_MOCK = {
    _LIGHT_DSUID: LightChannelState(
        brightness=80.0,
        color_temp_mired=250.0,
        hue=120.0,
        saturation=100.0,
        x=0.172,
        y=0.747,
    )
}


def _make_light_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="plan44", data=_DATA, options={})
    entry.add_to_hass(hass)
    subentry = ConfigSubentry(
        subentry_type=SUBENTRY_TYPE_P44_DEVICE,
        title="HueIris Kay",
        data=_LIGHT_SUBENTRY_DATA,
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    return entry


async def test_light_entity_created(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    entry = _make_light_entry(hass)
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_light_states",
        new=AsyncMock(return_value=_LIGHT_STATES_MOCK),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    entities = [
        e
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id and e.config_subentry_id is not None
    ]
    assert len(entities) == 1
    assert entities[0].domain == "light"


async def test_light_entity_state_reflects_poll(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    entry = _make_light_entry(hass)
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_light_states",
        new=AsyncMock(return_value=_LIGHT_STATES_MOCK),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    light_entry = next(
        e
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id and e.config_subentry_id is not None
    )
    state = hass.states.get(light_entry.entity_id)
    assert state is not None
    assert state.state == "on"
    assert state.attributes.get("brightness") == round(80.0 / 100 * 255)
    # XY takes priority over HS when both channels are present
    assert state.attributes.get("color_mode") == "xy"
    xy = state.attributes.get("xy_color")
    assert xy is not None
    assert round(xy[0], 3) == 0.172
    assert round(xy[1], 3) == 0.747


async def test_light_entity_unavailable_without_data(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    entry = _make_light_entry(hass)
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_light_states",
        new=AsyncMock(return_value={}),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    light_entry = next(
        e
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id and e.config_subentry_id is not None
    )
    state = hass.states.get(light_entry.entity_id)
    assert state is not None
    assert state.state == "unavailable"


async def test_light_entity_push_update(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """Push notification via async_apply_push_channel_states updates state."""
    entry = _make_light_entry(hass)
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_light_states",
        new=AsyncMock(return_value=_LIGHT_STATES_MOCK),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    device_coordinator = entry.runtime_data.device_coordinator
    assert device_coordinator is not None

    # Simulate a channelStates push notification from the plan44 bridge.
    push_msg = {
        "message": "channelStates",
        "dSUID": _LIGHT_DSUID,
        "channelStates": {
            "brightness": {"value": 40.0},
            "colortemp": {"value": 350.0},
            "hue": {"value": 240.0},
            "saturation": {"value": 80.0},
            "x": {"value": 0.3},
            "y": {"value": 0.6},
        },
    }
    device_coordinator.async_apply_push_channel_states(_LIGHT_DSUID, push_msg)
    await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    light_entry = next(
        e
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id and e.config_subentry_id is not None
    )
    state = hass.states.get(light_entry.entity_id)
    assert state is not None
    assert state.state == "on"
    assert state.attributes.get("brightness") == round(40.0 / 100 * 255)
    xy = state.attributes.get("xy_color")
    assert xy is not None
    assert round(xy[0], 1) == 0.3
    assert round(xy[1], 1) == 0.6


async def test_light_entity_push_update_unknown_dsuid_ignored(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """Push for an unknown dSUID does not affect known entity state."""
    entry = _make_light_entry(hass)
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_light_states",
        new=AsyncMock(return_value=_LIGHT_STATES_MOCK),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    device_coordinator = entry.runtime_data.device_coordinator
    assert device_coordinator is not None

    push_msg = {
        "message": "channelStates",
        "dSUID": "UNKNOWN_DSUID_00000000",
        "channelStates": {"brightness": {"value": 99.0}},
    }
    unknown = "UNKNOWN_DSUID_00000000"
    device_coordinator.async_apply_push_channel_states(unknown, push_msg)
    await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    light_entry = next(
        e
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id and e.config_subentry_id is not None
    )
    state = hass.states.get(light_entry.entity_id)
    # State should still reflect the original poll data
    assert state is not None
    assert state.attributes.get("brightness") == round(80.0 / 100 * 255)


async def test_light_entity_linked_to_subentry(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    entry = _make_light_entry(hass)
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_light_states",
        new=AsyncMock(return_value=_LIGHT_STATES_MOCK),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    subentry_id = next(iter(entry.subentries))
    registry = async_get_entity_registry(hass)
    ents = [
        e
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id and e.config_subentry_id is not None
    ]
    assert len(ents) == 1
    assert ents[0].config_subentry_id == subentry_id


async def test_sensor_entity_push_update(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """Push via async_apply_push_sensor_states updates sensor entity state."""
    entry = _make_entry(hass)
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_states",
        new=AsyncMock(return_value=_STATES),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    device_coordinator = entry.runtime_data.device_coordinator
    assert device_coordinator is not None

    push_msg = {
        "message": "sensorStates",
        "dSUID": _DSUID,
        "sensorStates": {"temperature": {"value": 24.0}},
        "binaryInputStates": {"low_battery": {"value": True}},
    }
    device_coordinator.async_apply_push_sensor_states(_DSUID, push_msg)
    await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    sensor_entry = next(
        e
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id
        and e.config_subentry_id is not None
        and e.domain == "sensor"
    )
    state = hass.states.get(sensor_entry.entity_id)
    assert state is not None
    assert float(state.state) == 24.0

    binary_entry = next(
        e
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id
        and e.config_subentry_id is not None
        and e.domain == "binary_sensor"
    )
    binary_state = hass.states.get(binary_entry.entity_id)
    assert binary_state is not None
    assert binary_state.state == "on"


async def test_sensor_entity_push_update_unknown_dsuid_ignored(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """Push for an unknown dSUID does not affect known sensor entity state."""
    entry = _make_entry(hass)
    with patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_states",
        new=AsyncMock(return_value=_STATES),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    device_coordinator = entry.runtime_data.device_coordinator
    assert device_coordinator is not None

    push_msg = {
        "message": "sensorStates",
        "dSUID": "UNKNOWN_DSUID_00000000",
        "sensorStates": {"temperature": {"value": 99.0}},
    }
    unknown = "UNKNOWN_DSUID_00000000"
    device_coordinator.async_apply_push_sensor_states(unknown, push_msg)
    await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    sensor_entry = next(
        e
        for e in registry.entities.values()
        if e.config_entry_id == entry.entry_id
        and e.config_subentry_id is not None
        and e.domain == "sensor"
    )
    state = hass.states.get(sensor_entry.entity_id)
    assert state is not None
    # Original poll value must be unchanged
    assert float(state.state) == 21.5
