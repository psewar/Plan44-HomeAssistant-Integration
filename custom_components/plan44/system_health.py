from __future__ import annotations

from typing import cast

from homeassistant.components import system_health
from homeassistant.core import HomeAssistant

from .const import DOMAIN, Plan44ConfigEntry


async def async_register(
    hass: HomeAssistant,
    register: system_health.SystemHealthRegistration,
) -> None:
    register.async_register_info(system_health_info)


async def system_health_info(hass: HomeAssistant) -> dict[str, object]:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return {"configured_entries": 0}

    entry = cast(Plan44ConfigEntry, entries[0])
    runtime = getattr(entry, "runtime_data", None)
    if runtime is None:
        # Entry present but not loaded (e.g. failed setup).
        return {"configured_entries": len(entries), "connected": False}

    exports = runtime.store.data.get("exports", {})
    return {
        "configured_entries": len(entries),
        "connected": runtime.client.is_connected,
        "mapped_exports": len(exports),
    }
