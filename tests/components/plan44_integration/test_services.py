from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.plan44_integration.const import DOMAIN


async def test_create_virtual_device_service(
    hass: HomeAssistant, config_entry, mock_plan44_client, entity_registry
) -> None:
    hass.states.async_set("switch.test_switch", "off")
    entity_registry.async_get_or_create(
        "switch",
        "test_platform",
        "unique_switch_1",
        suggested_object_id="test_switch",
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        "create_virtual_device",
        {
            "entity_id": "switch.test_switch",
            "kind": "switch",
            "name": "Test Switch",
            "allow_reverse": True,
        },
        blocking=True,
    )

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    store = entry.runtime_data.store
    export = store.get_export("switch.test_switch")

    assert export is not None
    assert export["kind"] == "switch"
    mock_plan44_client.async_register_switch_like.assert_awaited()
    mock_plan44_client.async_push_channel_value.assert_awaited()


async def test_push_entity_state_service(
    hass: HomeAssistant, config_entry, mock_plan44_client, entity_registry
) -> None:
    hass.states.async_set("switch.test_switch", "on")
    entity_registry.async_get_or_create(
        "switch",
        "test_platform",
        "unique_switch_2",
        suggested_object_id="test_switch",
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(
        DOMAIN,
        "create_virtual_device",
        {
            "entity_id": "switch.test_switch",
            "kind": "switch",
            "name": "Test Switch",
            "allow_reverse": True,
        },
        blocking=True,
    )

    mock_plan44_client.async_push_channel_value.reset_mock()

    await hass.services.async_call(
        DOMAIN,
        "push_entity_state",
        {"entity_id": "switch.test_switch"},
        blocking=True,
    )

    mock_plan44_client.async_push_channel_value.assert_awaited()
