from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from custom_components.plan44.const import (
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
)

TEST_ENTRY_DATA = {
    CONF_HOST: "127.0.0.1",
    CONF_PORT: 8999,
    CONF_VDC_MODEL_NAME: DEFAULT_VDC_MODEL_NAME,
    CONF_AUTO_REPUBLISH: DEFAULT_AUTO_REPUBLISH,
    CONF_REVERSE_ENABLED: DEFAULT_REVERSE_ENABLED,
    CONF_RECONNECT_INTERVAL: DEFAULT_RECONNECT_INTERVAL,
    CONF_BLOCKLIST_INTEGRATIONS: DEFAULT_BLOCKLIST_INTEGRATIONS,
    CONF_BLOCKLIST_ENTITY_ID_PREFIXES: DEFAULT_BLOCKLIST_ENTITY_ID_PREFIXES,
}


@pytest.fixture
def mock_plan44_client() -> Any:
    with patch(
        "custom_components.plan44.__init__.Plan44Client",
        autospec=True,
    ) as client_cls:
        client = client_cls.return_value
        client.async_connect = AsyncMock()
        client.async_disconnect = AsyncMock()
        client.async_ensure_connected = AsyncMock()
        client.async_register_switch_like = AsyncMock()
        client.async_register_sensor = AsyncMock()
        client.async_push_channel_value = AsyncMock()
        client.async_push_sensor_value = AsyncMock()
        client.is_connected = True
        yield client


@pytest.fixture
async def config_entry(hass: HomeAssistant) -> Any:
    entry = hass.config_entries.async_add(
        cast(
            Any,
            {
                "version": 1,
                "domain": DOMAIN,
                "title": "plan44 (127.0.0.1)",
                "data": TEST_ENTRY_DATA,
                "options": {},
            },
        )
    )
    return entry


@pytest.fixture
def entity_registry(hass: HomeAssistant) -> er.EntityRegistry:
    return er.async_get(hass)
