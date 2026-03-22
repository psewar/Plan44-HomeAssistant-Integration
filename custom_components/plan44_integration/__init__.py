from __future__ import annotations

import logging
from typing import Any, cast

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.typing import ConfigType

from .const import (
    ATTR_ALLOW_REVERSE,
    ATTR_ENTITY_ID,
    ATTR_ENTRY_ID,
    ATTR_KIND,
    ATTR_NAME,
    ATTR_ROOM_HINT,
    CONF_AUTO_REPUBLISH,
    CONF_HOST,
    CONF_PORT,
    CONF_REVERSE_ENABLED,
    CONF_VDC_MODEL_NAME,
    DOMAIN,
    SERVICE_CREATE_VIRTUAL_DEVICE,
    SERVICE_PUSH_ENTITY_STATE,
    SERVICE_REMOVE_VIRTUAL_DEVICE,
    SERVICE_REPUBLISH_VIRTUAL_DEVICES,
    SUPPORTED_KINDS,
    Plan44ConfigEntry,
    Plan44RuntimeData,
)
from .coordinator import Plan44Coordinator
from .plan44_client import Plan44Client
from .store import Plan44Store

_LOGGER = logging.getLogger(__name__)

CREATE_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): str,
        vol.Required(ATTR_ENTITY_ID): str,
        vol.Required(ATTR_KIND): vol.In(SUPPORTED_KINDS),
        vol.Optional(ATTR_NAME): str,
        vol.Optional(ATTR_ROOM_HINT): str,
        vol.Optional(ATTR_ALLOW_REVERSE, default=True): bool,
    }
)

REMOVE_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): str,
        vol.Required(ATTR_ENTITY_ID): str,
    }
)
PUSH_STATE_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_ENTRY_ID): str,
        vol.Required(ATTR_ENTITY_ID): str,
    }
)
REPUBLISH_SCHEMA = vol.Schema({vol.Optional(ATTR_ENTRY_ID): str})


def _resolve_entry(hass: HomeAssistant, call: ServiceCall) -> Plan44ConfigEntry:
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        raise HomeAssistantError("No configured plan44 entry found")

    requested_entry_id = cast(str | None, call.data.get(ATTR_ENTRY_ID))
    if requested_entry_id is not None:
        for entry in entries:
            if entry.entry_id == requested_entry_id:
                return cast(Plan44ConfigEntry, entry)
        raise HomeAssistantError(f"Unknown plan44 entry_id: {requested_entry_id}")

    if len(entries) > 1:
        raise HomeAssistantError(
            "Multiple plan44 entries configured; specify entry_id in the service call"
        )

    return cast(Plan44ConfigEntry, entries[0])


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async def _svc_create_virtual_device(call: ServiceCall) -> None:
        entry = _resolve_entry(hass, call)
        entity_id = cast(str, call.data[ATTR_ENTITY_ID])
        kind = cast(str, call.data[ATTR_KIND])
        name = cast(str | None, call.data.get(ATTR_NAME))
        room_hint = cast(str | None, call.data.get(ATTR_ROOM_HINT))
        allow_reverse = cast(bool, call.data[ATTR_ALLOW_REVERSE])

        await entry.runtime_data.coordinator.async_create_virtual_device(
            entity_id=entity_id,
            kind=kind,
            name=name,
            room_hint=room_hint,
            allow_reverse=allow_reverse,
        )

    async def _svc_remove_virtual_device(call: ServiceCall) -> None:
        entry = _resolve_entry(hass, call)
        entity_id = cast(str, call.data[ATTR_ENTITY_ID])
        await entry.runtime_data.coordinator.async_remove_virtual_device(
            entity_id=entity_id,
        )

    async def _svc_republish_virtual_devices(call: ServiceCall) -> None:
        entry = _resolve_entry(hass, call)
        await entry.runtime_data.coordinator.async_republish_virtual_devices()

    async def _svc_push_entity_state(call: ServiceCall) -> None:
        entry = _resolve_entry(hass, call)
        entity_id = cast(str, call.data[ATTR_ENTITY_ID])
        await entry.runtime_data.coordinator.async_forward_entity_state(
            entity_id=entity_id,
            force=True,
        )

    if not hass.services.has_service(DOMAIN, SERVICE_CREATE_VIRTUAL_DEVICE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_CREATE_VIRTUAL_DEVICE,
            _svc_create_virtual_device,
            schema=CREATE_DEVICE_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_REMOVE_VIRTUAL_DEVICE,
            _svc_remove_virtual_device,
            schema=REMOVE_DEVICE_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_REPUBLISH_VIRTUAL_DEVICES,
            _svc_republish_virtual_devices,
            schema=REPUBLISH_SCHEMA,
        )
        hass.services.async_register(
            DOMAIN,
            SERVICE_PUSH_ENTITY_STATE,
            _svc_push_entity_state,
            schema=PUSH_STATE_SCHEMA,
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: Plan44ConfigEntry) -> bool:
    store = Plan44Store(hass, entry)
    await store.async_load()

    coordinator: Plan44Coordinator | None = None

    async def _incoming_callback(msg: dict[str, Any]) -> None:
        if coordinator is not None:
            await coordinator.async_handle_plan44_message(msg)

    async def _disconnect_callback() -> None:
        if coordinator is not None:
            await coordinator.async_handle_disconnect()

    client = Plan44Client(
        host=cast(str, entry.data[CONF_HOST]),
        port=cast(int, entry.data[CONF_PORT]),
        vdc_model_name=cast(str, entry.data[CONF_VDC_MODEL_NAME]),
        incoming_callback=_incoming_callback,
        disconnect_callback=_disconnect_callback,
    )

    coordinator = Plan44Coordinator(
        hass=hass,
        entry=entry,
        client=client,
        store=store,
        reverse_enabled=cast(
            bool,
            entry.options.get(
                CONF_REVERSE_ENABLED,
                entry.data[CONF_REVERSE_ENABLED],
            ),
        ),
        auto_republish=cast(
            bool,
            entry.options.get(
                CONF_AUTO_REPUBLISH,
                entry.data[CONF_AUTO_REPUBLISH],
            ),
        ),
    )

    try:
        await coordinator.async_initialize()
    except Exception as err:
        raise ConfigEntryNotReady(f"Unable to connect to plan44: {err}") from err

    entry.runtime_data = Plan44RuntimeData(
        client=client,
        coordinator=coordinator,
        store=store,
    )

    entry.async_on_unload(
        lambda: _LOGGER.debug("Unloading plan44 entry %s", entry.entry_id)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: Plan44ConfigEntry) -> bool:
    await entry.runtime_data.coordinator.async_shutdown()
    return True
