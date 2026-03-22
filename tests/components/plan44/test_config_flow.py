from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from custom_components.plan44.const import DOMAIN


async def test_user_flow_success(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.plan44.config_flow._validate_connection",
        new=AsyncMock(),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "host": "127.0.0.1",
                "port": 8999,
                "vdc_model_name": "Home Assistant Bridge",
                "auto_republish": True,
                "reverse_enabled": True,
                "reconnect_interval": 10,
                "blocklist_integrations": "",
                "blocklist_entity_id_prefixes": "",
            },
        )

    result2 = cast(Any, result2)
    assert result2["type"] == "create_entry"
    assert result2["title"] == "plan44 (127.0.0.1)"


async def test_user_flow_cannot_connect(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.plan44.config_flow._validate_connection",
        new=AsyncMock(side_effect=OSError),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "host": "127.0.0.1",
                "port": 8999,
                "vdc_model_name": "Home Assistant Bridge",
                "auto_republish": True,
                "reverse_enabled": True,
                "reconnect_interval": 10,
                "blocklist_integrations": "",
                "blocklist_entity_id_prefixes": "",
            },
        )

    result2 = cast(Any, result2)
    assert result2["type"] == "form"
    assert result2["errors"] == {"base": "cannot_connect"}


async def test_options_flow_opens(
    hass: HomeAssistant,
    config_entry: Any,
) -> None:
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    result = await hass.config_entries.options.async_init(config_entry.entry_id)

    result = cast(Any, result)
    assert result["type"] == "form"
    assert result["step_id"] == "init"
