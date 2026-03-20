from __future__ import annotations

from homeassistant.components.diagnostics import async_redact_data

from .const import CONF_HOST, CONF_PORT, CONF_VDC_MODEL_NAME, Plan44ConfigEntry

TO_REDACT = {
    CONF_HOST,
    CONF_PORT,
    CONF_VDC_MODEL_NAME,
}


async def async_get_config_entry_diagnostics(hass, entry: Plan44ConfigEntry):
    runtime = entry.runtime_data

    data = {
        "entry_data": dict(entry.data),
        "entry_options": dict(entry.options),
        "exports": runtime.store.data,
        "client_connected": runtime.client.is_connected,
    }

    return async_redact_data(data, TO_REDACT)
