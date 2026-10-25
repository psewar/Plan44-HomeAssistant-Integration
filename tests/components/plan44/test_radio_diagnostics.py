"""HA integration tests for the radio diagnostics of wireless bridge devices."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigSubentry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
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
    CONF_RADIO_DIAGNOSTICS,
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
    SUBENTRY_TYPE_P44_DEVICE,
)
from custom_components.plan44.web_client import (
    Plan44WebApi,
    Plan44WebApiError,
    RadioState,
)

_DATA = {
    CONF_HOST: "127.0.0.1",
    CONF_PORT: 8999,
    CONF_VDC_MODEL_NAME: DEFAULT_VDC_MODEL_NAME,
    CONF_AUTO_REPUBLISH: DEFAULT_AUTO_REPUBLISH,
    CONF_REVERSE_ENABLED: DEFAULT_REVERSE_ENABLED,
    CONF_RECONNECT_INTERVAL: DEFAULT_RECONNECT_INTERVAL,
    CONF_BLOCKLIST_INTEGRATIONS: DEFAULT_BLOCKLIST_INTEGRATIONS,
    CONF_BLOCKLIST_ENTITY_ID_PREFIXES: DEFAULT_BLOCKLIST_ENTITY_ID_PREFIXES,
    CONF_WEB_USER: "user",
    CONF_WEB_PASSWORD: "secret",
}

_VALVE = "VALVE-A52006"
_DEAD_VALVE = "VALVE-A52001"
_SMOKE = "SMOKE-D21430"
_PACKET = datetime(2026, 10, 24, 23, 29, 53, tzinfo=UTC)

_SENSOR_KEYS = (
    "last_radio_packet",
    "packet_interval",
    "rssi",
    "repeater_count",
    "op_state",
)


def _radio(
    dsuid: str,
    name: str,
    *,
    active: bool | None = True,
    last_packet: datetime | None = _PACKET,
    rssi: int | None = -71,
    repeater_count: int | None = 1,
    has_repeater_count: bool = True,
    op_state: str | None = "-71dBm1 Rep., ",
    low_battery: bool | None = False,
    has_low_battery: bool = True,
) -> RadioState:
    return RadioState(
        dsuid=dsuid,
        name=name,
        model="Micropelt EnOcean heating valve actuator (A5-20-06)",
        active=active,
        last_packet=last_packet,
        rssi=rssi,
        repeater_count=repeater_count,
        has_repeater_count=has_repeater_count,
        op_state=op_state,
        low_battery=low_battery,
        has_low_battery=has_low_battery,
    )


_RADIO = {
    _VALVE: _radio(_VALVE, "MVA009 Living Room"),
    # Timed out and not heard since the bridge started.
    _DEAD_VALVE: _radio(
        _DEAD_VALVE,
        "MVA004 Office",
        active=False,
        last_packet=None,
        rssi=None,
        repeater_count=None,
        op_state="timeout, unseen",
        low_battery=None,
    ),
}


def _make_entry(hass: HomeAssistant, radio_diagnostics: bool = True) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="plan44",
        data=_DATA,
        options={CONF_RADIO_DIAGNOSTICS: radio_diagnostics},
    )
    entry.add_to_hass(hass)
    return entry


def _import_smoke_detector(hass: HomeAssistant, entry: MockConfigEntry) -> str:
    """Add the smoke detector as a picker-imported device; returns its sub-entry id."""
    subentry = ConfigSubentry(
        subentry_type=SUBENTRY_TYPE_P44_DEVICE,
        title="Smoke detector hall",
        data=MappingProxyType(
            {
                ATTR_DSUID: _SMOKE,
                # Renamed on import: the device must keep this name.
                ATTR_NAME: "Smoke detector hall",
                ATTR_MODEL: "Nexelec EnOcean Temperature sensor (D2-14-30)",
                ATTR_CHANNELS: [
                    {
                        "key": "temperature",
                        "name": "Temperature",
                        "platform": "sensor",
                        "unit": "°C",
                        "device_class": "temperature",
                        "state_class": "measurement",
                    }
                ],
            }
        ),
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(entry, subentry)
    return subentry.subentry_id


def _entity_id(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    entity_id = async_get_entity_registry(hass).async_get_entity_id(
        domain, DOMAIN, unique_id
    )
    assert entity_id is not None, f"no {domain} entity with unique_id {unique_id}"
    return entity_id


def _state(hass: HomeAssistant, entity_id: str) -> str:
    st = hass.states.get(entity_id)
    assert st is not None, f"{entity_id} does not exist"
    return st.state


def _radio_patch(**kwargs: Any) -> Any:
    return patch(
        "custom_components.plan44.web_client.Plan44WebApi.async_get_radio_states",
        new=AsyncMock(**kwargs),
    )


async def test_radio_diagnostics_are_off_by_default(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """Without the option nothing new is polled and no entity appears."""
    entry = _make_entry(hass, radio_diagnostics=False)
    _import_smoke_detector(hass, entry)
    with (
        patch(
            "custom_components.plan44.web_client.Plan44WebApi.async_get_states",
            new=AsyncMock(return_value={_SMOKE: {"sensor": {"temperature": 22.6}}}),
        ),
        _radio_patch(return_value=_RADIO) as radio_poll,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    radio_poll.assert_not_awaited()
    unique_ids = {
        e.unique_id for e in async_get_entity_registry(hass).entities.values()
    }
    assert not any(uid.endswith("_last_radio_packet") for uid in unique_ids)
    assert not any(uid.endswith("_active") for uid in unique_ids)


async def test_every_radio_device_gets_diagnostic_entities(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """Nothing imported: each radio device still gets its own diagnostics device."""
    entry = _make_entry(hass)
    with _radio_patch(return_value=_RADIO):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    for dsuid in (_VALVE, _DEAD_VALVE):
        ids = [
            _entity_id(hass, "sensor", f"{entry.entry_id}_{dsuid}_{key}")
            for key in _SENSOR_KEYS
        ]
        ids.append(
            _entity_id(hass, "binary_sensor", f"{entry.entry_id}_{dsuid}_active")
        )
        for entity_id in ids:
            reg = registry.async_get(entity_id)
            assert reg is not None
            assert reg.entity_category is EntityCategory.DIAGNOSTIC
            # Not imported, so not attributed to any sub-entry.
            assert reg.config_subentry_id is None

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, _VALVE)})
    assert device is not None
    assert device.name == "MVA009 Living Room"
    assert device.model == "Micropelt EnOcean heating valve actuator (A5-20-06)"
    assert device.manufacturer == "plan44"
    assert (
        _entity_id(hass, "sensor", f"{entry.entry_id}_{_VALVE}_last_radio_packet")
        == "sensor.mva009_living_room_last_radio_packet"
    )


async def test_radio_entities_show_what_the_bridge_reports(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    entry = _make_entry(hass)
    with _radio_patch(return_value=_RADIO):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    def entity(domain: str, dsuid: str, key: str) -> str:
        return _entity_id(hass, domain, f"{entry.entry_id}_{dsuid}_{key}")

    assert _state(hass, entity("sensor", _VALVE, "last_radio_packet")) == (
        "2026-10-24T23:29:53+00:00"
    )
    rssi = hass.states.get(entity("sensor", _VALVE, "rssi"))
    assert rssi is not None
    assert rssi.state == "-71"
    assert rssi.attributes.get("unit_of_measurement") == "dBm"
    assert rssi.attributes.get("device_class") == "signal_strength"
    assert _state(hass, entity("sensor", _VALVE, "repeater_count")) == "1"
    assert _state(hass, entity("sensor", _VALVE, "op_state")) == "-71dBm1 Rep., "
    assert _state(hass, entity("binary_sensor", _VALVE, "active")) == "on"

    # Silent since the bridge started: unknown, not a made-up time — and still
    # available, because "silent" is exactly what the entity has to show.
    assert _state(hass, entity("sensor", _DEAD_VALVE, "last_radio_packet")) == "unknown"
    assert _state(hass, entity("sensor", _DEAD_VALVE, "rssi")) == "unknown"
    assert _state(hass, entity("binary_sensor", _DEAD_VALVE, "active")) == "off"
    assert _state(hass, entity("sensor", _DEAD_VALVE, "op_state")) == "timeout, unseen"


async def test_radio_without_repeaters_gets_no_repeater_entity(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    entry = _make_entry(hass)
    eldat = _radio("ELDAT1", "Eldat", repeater_count=None, has_repeater_count=False)
    with _radio_patch(return_value={"ELDAT1": eldat}):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    uid = f"{entry.entry_id}_ELDAT1_repeater_count"
    assert registry.async_get_entity_id("sensor", DOMAIN, uid) is None
    _entity_id(hass, "sensor", f"{entry.entry_id}_ELDAT1_last_radio_packet")


async def test_imported_device_keeps_its_device_and_sub_entry(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """The diagnostics join the imported device instead of creating a second one."""
    entry = _make_entry(hass)
    subentry_id = _import_smoke_detector(hass, entry)
    # The bridge's own name differs from the one chosen on import.
    radio = {**_RADIO, _SMOKE: _radio(_SMOKE, "SmokeHall", repeater_count=0)}
    with (
        patch(
            "custom_components.plan44.web_client.Plan44WebApi.async_get_states",
            new=AsyncMock(return_value={_SMOKE: {"sensor": {"temperature": 22.6}}}),
        ),
        _radio_patch(return_value=radio),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    channel = registry.async_get(
        _entity_id(hass, "sensor", f"{entry.entry_id}_{subentry_id}_temperature")
    )
    packet = registry.async_get(
        _entity_id(hass, "sensor", f"{entry.entry_id}_{_SMOKE}_last_radio_packet")
    )
    active = registry.async_get(
        _entity_id(hass, "binary_sensor", f"{entry.entry_id}_{_SMOKE}_active")
    )
    assert channel is not None and packet is not None and active is not None
    assert packet.device_id == channel.device_id == active.device_id
    assert packet.config_subentry_id == subentry_id
    assert active.config_subentry_id == subentry_id

    device = dr.async_get(hass).async_get_device(identifiers={(DOMAIN, _SMOKE)})
    assert device is not None
    assert device.name == "Smoke detector hall"  # the import's name, not the bridge's
    # Only the import sub-entry, not also the "no sub-entry" bucket.
    assert device.config_entries_subentries == {entry.entry_id: {subentry_id}}


async def test_device_learned_later_appears_on_the_next_poll(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    entry = _make_entry(hass)
    first = {_VALVE: _RADIO[_VALVE]}
    with _radio_patch(side_effect=[first, _RADIO]):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        uid = f"{entry.entry_id}_{_DEAD_VALVE}_last_radio_packet"
        registry = async_get_entity_registry(hass)
        assert registry.async_get_entity_id("sensor", DOMAIN, uid) is None

        dc = entry.runtime_data.device_coordinator
        assert dc is not None
        await dc.async_refresh()
        await hass.async_block_till_done()

    assert _state(hass, _entity_id(hass, "sensor", uid)) == "unknown"


async def test_poll_jitter_does_not_move_the_last_packet(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """The same packet must not change the state on every poll; a new one must."""
    entry = _make_entry(hass)
    polls = [
        {_VALVE: _radio(_VALVE, "MVA009 Living Room", last_packet=_PACKET + delta)}
        for delta in (timedelta(0), timedelta(seconds=1), timedelta(minutes=2))
    ]
    with _radio_patch(side_effect=polls):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entity_id = _entity_id(
            hass, "sensor", f"{entry.entry_id}_{_VALVE}_last_radio_packet"
        )
        first = hass.states.get(entity_id)
        assert first is not None
        assert first.state == "2026-10-24T23:29:53+00:00"

        dc = entry.runtime_data.device_coordinator
        assert dc is not None
        await dc.async_refresh()  # same packet, measured a second later
        await hass.async_block_till_done()
        same = hass.states.get(entity_id)
        assert same is not None
        assert same.state == first.state
        assert same.last_changed == first.last_changed

        await dc.async_refresh()  # a real new packet
        await hass.async_block_till_done()

    assert _state(hass, entity_id) == "2026-10-24T23:31:53+00:00"


async def test_packet_interval_shows_the_minutes_between_packets(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """An hourly valve reads ~60 min; unknown until two packets were seen."""
    entry = _make_entry(hass)
    polls = [
        {_VALVE: _radio(_VALVE, "MVA009 Living Room", last_packet=_PACKET + delta)}
        for delta in (timedelta(0), timedelta(seconds=1), timedelta(minutes=60))
    ]
    with _radio_patch(side_effect=polls):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entity_id = _entity_id(
            hass, "sensor", f"{entry.entry_id}_{_VALVE}_packet_interval"
        )
        assert _state(hass, entity_id) == "unknown"

        dc = entry.runtime_data.device_coordinator
        assert dc is not None
        await dc.async_refresh()  # same packet again: still no interval
        await hass.async_block_till_done()
        assert _state(hass, entity_id) == "unknown"

        await dc.async_refresh()  # the next packet, an hour later
        await hass.async_block_till_done()

    state = hass.states.get(entity_id)
    assert state is not None
    assert float(state.state) == 60.0
    assert state.attributes.get("unit_of_measurement") == "min"
    assert state.attributes.get("device_class") == "duration"
    reg = async_get_entity_registry(hass).async_get(entity_id)
    assert reg is not None and reg.entity_category is EntityCategory.DIAGNOSTIC


async def test_radio_entities_unavailable_while_the_bridge_is_unreachable(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    entry = _make_entry(hass)
    with _radio_patch(side_effect=[_RADIO, Plan44WebApiError("boom"), _RADIO]):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        entity_id = _entity_id(
            hass, "binary_sensor", f"{entry.entry_id}_{_VALVE}_active"
        )
        assert _state(hass, entity_id) == "on"

        dc = entry.runtime_data.device_coordinator
        assert dc is not None
        await dc.async_refresh()
        await hass.async_block_till_done()
        assert _state(hass, entity_id) == "unavailable"

        await dc.async_refresh()
        await hass.async_block_till_done()

    assert _state(hass, entity_id) == "on"


async def test_device_removed_from_the_bridge_becomes_unavailable(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    entry = _make_entry(hass)
    with _radio_patch(side_effect=[_RADIO, {_VALVE: _RADIO[_VALVE]}]):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        dc = entry.runtime_data.device_coordinator
        assert dc is not None
        await dc.async_refresh()
        await hass.async_block_till_done()

    gone = _entity_id(hass, "sensor", f"{entry.entry_id}_{_DEAD_VALVE}_op_state")
    assert _state(hass, gone) == "unavailable"
    still = _entity_id(hass, "sensor", f"{entry.entry_id}_{_VALVE}_op_state")
    assert _state(hass, still) == "-71dBm1 Rep., "


async def test_radio_query_asks_the_bridge_for_the_radio_properties() -> None:
    """Regression guard: a property missing from the query is silently None."""
    captured: dict[str, Any] = {}

    async def fake_executor(func: Any, query: Any) -> Any:
        captured["query"] = query
        return {"result": {}}

    fake_hass = cast(Any, MagicMock())
    fake_hass.async_add_executor_job = fake_executor
    api = Plan44WebApi(fake_hass, "https://bridge.invalid", "user", "pw")

    assert await api.async_get_radio_states() == {}

    device_query = captured["query"]["query"]["x-p44-vdcs"]["*"]["x-p44-devices"]["*"]
    assert {
        "dSUID",
        "name",
        "model",
        "active",
        "x-p44-packetAge",
        "x-p44-rssi",
        "x-p44-repeaterCount",
        "x-p44-opStateText",
        "binaryInputDescriptions",
        "binaryInputStates",
    } <= set(device_query)
    # Narrowed to what the low-battery status needs (half the reply size).
    assert device_query["binaryInputDescriptions"] == {"*": {"sensorFunction": None}}
    assert device_query["binaryInputStates"] == {"*": {"value": None}}


async def test_low_battery_shows_for_radio_devices_that_have_the_input(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """A valve's energy store, as a diagnostic battery sensor."""
    entry = _make_entry(hass)
    rocker = _radio("ROCKER", "Rocker", has_low_battery=False, low_battery=None)
    drained = {
        **_RADIO,
        "ROCKER": rocker,
        _VALVE: _radio(_VALVE, "MVA009 Living Room", low_battery=True),
    }
    with _radio_patch(side_effect=[{**_RADIO, "ROCKER": rocker}, drained]):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

        entity_id = _entity_id(
            hass, "binary_sensor", f"{entry.entry_id}_{_VALVE}_low_battery"
        )
        state = hass.states.get(entity_id)
        assert state is not None
        assert state.state == "off"
        assert state.attributes.get("device_class") == "battery"
        reg = async_get_entity_registry(hass).async_get(entity_id)
        assert reg is not None and reg.entity_category is EntityCategory.DIAGNOSTIC
        # No fresh value from the bridge: unknown, not "fine".
        dead = f"{entry.entry_id}_{_DEAD_VALVE}_low_battery"
        assert _state(hass, _entity_id(hass, "binary_sensor", dead)) == "unknown"
        # A device without the input gets none.
        assert (
            async_get_entity_registry(hass).async_get_entity_id(
                "binary_sensor", DOMAIN, f"{entry.entry_id}_ROCKER_low_battery"
            )
            is None
        )

        dc = entry.runtime_data.device_coordinator
        assert dc is not None
        await dc.async_refresh()
        await hass.async_block_till_done()

    assert _state(hass, entity_id) == "on"


async def test_imported_device_gets_no_second_low_battery_entity(
    hass: HomeAssistant, mock_plan44_client: Any
) -> None:
    """The import already shows its low-battery input as a channel entity."""
    entry = _make_entry(hass)
    _import_smoke_detector(hass, entry)
    radio = {**_RADIO, _SMOKE: _radio(_SMOKE, "SmokeHall", repeater_count=0)}
    with (
        patch(
            "custom_components.plan44.web_client.Plan44WebApi.async_get_states",
            new=AsyncMock(return_value={_SMOKE: {"sensor": {"temperature": 22.6}}}),
        ),
        _radio_patch(return_value=radio),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    registry = async_get_entity_registry(hass)
    uid = f"{entry.entry_id}_{_SMOKE}_low_battery"
    assert registry.async_get_entity_id("binary_sensor", DOMAIN, uid) is None
    # ...while the radio diagnostics themselves are there.
    _entity_id(hass, "binary_sensor", f"{entry.entry_id}_{_SMOKE}_active")


async def test_options_flow_offers_radio_diagnostics(
    hass: HomeAssistant, config_entry: Any, mock_plan44_client: Any
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = cast(
        Any, await hass.config_entries.options.async_init(config_entry.entry_id)
    )
    assert result["type"] == "form"
    fields = {str(key): key for key in result["data_schema"].schema}
    assert CONF_RADIO_DIAGNOSTICS in fields
    assert fields[CONF_RADIO_DIAGNOSTICS].default() is False

    result2 = cast(
        Any,
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_RADIO_DIAGNOSTICS: True}
        ),
    )
    assert result2["type"] == "create_entry"
    await hass.async_block_till_done()
    assert config_entry.options[CONF_RADIO_DIAGNOSTICS] is True
