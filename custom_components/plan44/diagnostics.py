from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_VDC_MODEL_NAME,
    CONF_WEB_PASSWORD,
    CONF_WEB_USER,
    Plan44ConfigEntry,
)

# Diagnostics are downloaded and routinely shared (issues, forums), so anything
# secret or identifying must be redacted.  The web password is the critical one;
# the user name and host/port are redacted as a courtesy.
TO_REDACT = {
    CONF_HOST,
    CONF_PORT,
    CONF_VDC_MODEL_NAME,
    CONF_WEB_USER,
    CONF_WEB_PASSWORD,
}


async def async_get_config_entry_diagnostics(
    hass: Any,
    entry: Plan44ConfigEntry,
) -> dict[str, Any]:
    runtime = entry.runtime_data

    data: dict[str, Any] = {
        "entry_data": dict(entry.data),
        "entry_options": dict(entry.options),
        "exports": runtime.store.data,
        "client_connected": runtime.client.is_connected,
    }

    return async_redact_data(data, TO_REDACT)
