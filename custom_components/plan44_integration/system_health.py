from __future__ import annotations

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant

from .const import DOMAIN


async def async_register(hass: HomeAssistant, register: system_health.SystemHealthRegistration) -> None:
    register.async_register_info(system_health_info)


async def system_health_info(hass: HomeAssistant) -> dict:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return {"configured_entries": 0}

    entry = entries[0]
    runtime = entry.runtime_data
    return {
        "configured_entries": len(entries),
        "connected": runtime.client.is_connected,
        "mapped_exports": len(runtime.store.data.get("exports", {})),
    }
