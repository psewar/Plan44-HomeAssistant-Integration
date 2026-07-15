from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from custom_components.plan44.const import CONF_PUSH_ENABLED, DOMAIN


async def test_setup_entry(
    hass: HomeAssistant,
    config_entry: Any,
    mock_plan44_client: Any,
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.runtime_data is not None
    mock_plan44_client.async_connect.assert_awaited()


def _subscribe_sent(client: Any) -> bool:
    return any(
        call.args
        and isinstance(call.args[0], dict)
        and call.args[0].get("message") == "subscribe"
        for call in client.async_send.call_args_list
    )


async def test_push_enabled_subscribes(
    hass: HomeAssistant, config_entry: Any, mock_plan44_client: Any
) -> None:
    """With push enabled (default), the coordinator subscribes to push events."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert _subscribe_sent(mock_plan44_client)


async def test_push_disabled_skips_subscribe(
    hass: HomeAssistant, config_entry: Any, mock_plan44_client: Any
) -> None:
    """With push disabled, no subscribe is sent (poll-only mode)."""
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_PUSH_ENABLED: False}
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    assert not _subscribe_sent(mock_plan44_client)
