"""The diagnostics dump must not leak the web API credentials."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from custom_components.plan44.const import CONF_WEB_PASSWORD, CONF_WEB_USER
from custom_components.plan44.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redacts_web_credentials(
    hass: HomeAssistant, config_entry: Any, mock_plan44_client: Any
) -> None:
    """web_user / web_password are replaced with the redaction marker."""
    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            CONF_WEB_USER: "p44user",
            CONF_WEB_PASSWORD: "sup3rsecret",
        },
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, config_entry)

    assert diag["entry_data"][CONF_WEB_PASSWORD] == "**REDACTED**"
    assert diag["entry_data"][CONF_WEB_USER] == "**REDACTED**"
    # Belt-and-braces: the secret must not appear anywhere in the dump.
    assert "sup3rsecret" not in str(diag)
