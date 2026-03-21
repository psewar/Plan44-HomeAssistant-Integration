from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.plan44_integration.const import DOMAIN


async def test_setup_entry(
    hass: HomeAssistant,
    config_entry,
    mock_plan44_client,
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    entry = hass.config_entries.async_entries(DOMAIN)[0]
    assert entry.runtime_data is not None
    mock_plan44_client.async_connect.assert_awaited()
