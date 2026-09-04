from __future__ import annotations

import logging
from typing import Any, cast

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.typing import ConfigType

from .bridge_client import Plan44BridgeClient
from .bridge_protocol import BridgeUpdate
from .const import (
    ATTR_ALLOW_REVERSE,
    ATTR_ENTITY_ID,
    ATTR_ENTRY_ID,
    ATTR_KIND,
    ATTR_NAME,
    ATTR_ROOM_HINT,
    CONF_AUTO_REPUBLISH,
    CONF_BRIDGE_API_PORT,
    CONF_HOST,
    CONF_PORT,
    CONF_REALTIME_ENABLED,
    CONF_REVERSE_ENABLED,
    CONF_SSH_HOST,
    CONF_SSH_HOST_KEY,
    CONF_SSH_PORT,
    CONF_SSH_PRIVATE_KEY,
    CONF_SSH_USER,
    CONF_VDC_MODEL_NAME,
    CONF_VERIFY_SSL,
    CONF_WEB_CERT,
    CONF_WEB_PASSWORD,
    CONF_WEB_POLL_INTERVAL,
    CONF_WEB_USER,
    DEFAULT_BRIDGE_API_PORT,
    DEFAULT_SSH_PORT,
    DEFAULT_VERIFY_SSL,
    DEFAULT_WEB_POLL_INTERVAL,
    DOMAIN,
    SERVICE_CREATE_VIRTUAL_DEVICE,
    SERVICE_PUSH_ENTITY_STATE,
    SERVICE_REMOVE_VIRTUAL_DEVICE,
    SERVICE_REPUBLISH_VIRTUAL_DEVICES,
    SUPPORTED_KINDS,
    Plan44ConfigEntry,
    Plan44RuntimeData,
    signal_bridge_connection,
)
from .coordinator import Plan44Coordinator
from .device_coordinator import Plan44DeviceCoordinator
from .plan44_client import Plan44Client
from .store import Plan44Store
from .web_client import Plan44WebApi, default_web_url, fetch_server_cert_pem

PLATFORMS = ["binary_sensor", "light", "sensor"]

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


async def _async_handle_entry_updated(
    hass: HomeAssistant,
    entry: Plan44ConfigEntry,
) -> None:
    runtime = entry.runtime_data
    await runtime.coordinator.async_sync_runtime_exports()


async def _async_setup_web_api(
    hass: HomeAssistant, entry: Plan44ConfigEntry
) -> tuple[Plan44WebApi | None, Plan44DeviceCoordinator | None]:
    """Build the web API client + polling coordinator if web config is present.

    Only a web user + password are required; the URL defaults to ``https://<host>``
    (the same host entered during setup) unless explicitly overridden.
    """
    merged = {**entry.data, **entry.options}
    user = merged.get(CONF_WEB_USER)
    password = merged.get(CONF_WEB_PASSWORD)
    if not (user and password):
        return None, None
    url = default_web_url(merged.get(CONF_HOST))
    if not url:
        return None, None

    verify_ssl = bool(merged.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL))

    # Trust-on-first-use: pin the bridge's self-signed certificate so later
    # calls verify the peer. Fetch + persist it once; if it can't be fetched,
    # keep working unpinned and retry on the next setup.
    # Skipped entirely when verify_ssl is False.
    pinned_cert: str | None = None
    if verify_ssl:
        pinned_cert = merged.get(CONF_WEB_CERT)
        if not pinned_cert:
            pinned_cert = await hass.async_add_executor_job(fetch_server_cert_pem, url)
            if pinned_cert:
                hass.config_entries.async_update_entry(
                    entry, data={**entry.data, CONF_WEB_CERT: pinned_cert}
                )

    web_api = Plan44WebApi(
        hass,
        str(url),
        str(user),
        str(password),
        pinned_cert=pinned_cert,
        verify_ssl=verify_ssl,
    )
    interval = int(merged.get(CONF_WEB_POLL_INTERVAL, DEFAULT_WEB_POLL_INTERVAL))
    device_coordinator = Plan44DeviceCoordinator(hass, entry, web_api, interval)
    try:
        await device_coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        # Web API unreachable now — keep going; the coordinator will retry and
        # entities stay 'unknown' until a poll succeeds. The push/export paths
        # do not depend on the web API.
        _LOGGER.warning("plan44 web API not reachable yet; will retry polling")
    return web_api, device_coordinator


async def _async_setup_bridge_client(
    hass: HomeAssistant,
    entry: Plan44ConfigEntry,
    device_coordinator: Plan44DeviceCoordinator | None,
) -> Plan44BridgeClient | None:
    """Start the real-time bridge-API client (SSH tunnel) if configured.

    Pushes flow into the device coordinator, so imported entities update
    instantly.  Opt-in; the REST poll remains as fallback.
    """
    if device_coordinator is None:
        return None
    merged = {**entry.data, **entry.options}
    if not merged.get(CONF_REALTIME_ENABLED):
        return None
    ssh_user = merged.get(CONF_SSH_USER)
    ssh_key = merged.get(CONF_SSH_PRIVATE_KEY)
    if not (ssh_user and ssh_key):
        _LOGGER.warning(
            "plan44 real-time mode is enabled but the SSH user/key is missing; "
            "falling back to polling"
        )
        return None

    @callback
    def _on_update(update: BridgeUpdate) -> None:
        device_coordinator.apply_push_update(
            update.dsuid, update.group, update.key, update.value
        )

    @callback
    def _on_status(connected: bool) -> None:
        # Surface the real-time link state so a permanently dead tunnel is
        # visible instead of silently degrading to poll-only.
        _LOGGER.log(
            logging.INFO if connected else logging.WARNING,
            "plan44 real-time bridge link %s",
            "up" if connected else "down",
        )
        async_dispatcher_send(hass, signal_bridge_connection(entry.entry_id))

    @callback
    def _on_host_key(host_key: str) -> None:
        # Trust-on-first-use: persist the bridge host key so later tunnels pin it.
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_SSH_HOST_KEY: host_key}
        )

    client = Plan44BridgeClient(
        hass,
        ssh_host=str(merged.get(CONF_SSH_HOST) or merged.get(CONF_HOST)),
        ssh_port=int(merged.get(CONF_SSH_PORT, DEFAULT_SSH_PORT)),
        ssh_user=str(ssh_user),
        ssh_private_key=str(ssh_key),
        bridge_port=int(merged.get(CONF_BRIDGE_API_PORT, DEFAULT_BRIDGE_API_PORT)),
        on_update=_on_update,
        on_status=_on_status,
        pinned_host_key=merged.get(CONF_SSH_HOST_KEY) or None,
        on_host_key=_on_host_key,
    )
    await client.async_start()
    return client


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

    # async_initialize() opens the socket and starts the reader/keepalive tasks
    # and the state listener. Nothing owns those until the entry is fully set
    # up, so every failure path below must tear them down explicitly —
    # otherwise a setup retry leaks a coordinator whose (unbounded) reconnect
    # loop keeps running forever.
    try:
        await coordinator.async_initialize()
    except Exception as err:
        await coordinator.async_shutdown()
        raise ConfigEntryNotReady(f"Unable to connect to plan44: {err}") from err

    bridge_client: Plan44BridgeClient | None = None
    try:
        web_api, device_coordinator = await _async_setup_web_api(hass, entry)
        bridge_client = await _async_setup_bridge_client(
            hass, entry, device_coordinator
        )

        entry.runtime_data = Plan44RuntimeData(
            client=client,
            coordinator=coordinator,
            store=store,
            web_api=web_api,
            device_coordinator=device_coordinator,
            bridge_client=bridge_client,
        )

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        if bridge_client is not None:
            await bridge_client.async_stop()
        await coordinator.async_shutdown()
        raise

    entry.async_on_unload(entry.add_update_listener(_async_handle_entry_updated))
    entry.async_on_unload(
        lambda: _LOGGER.debug("Unloading plan44 entry %s", entry.entry_id)
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: Plan44ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    # Always tear the connections down, even if a platform refused to unload —
    # leaving the SSH tunnel / TCP client running would leak them on reload.
    runtime = entry.runtime_data
    if runtime.bridge_client is not None:
        await runtime.bridge_client.async_stop()
    await runtime.coordinator.async_shutdown()
    return unloaded
