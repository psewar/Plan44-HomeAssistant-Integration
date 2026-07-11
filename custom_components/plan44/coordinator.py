from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from .device_coordinator import Plan44DeviceCoordinator

from homeassistant.components import persistent_notification
from homeassistant.components.light import ATTR_BRIGHTNESS
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    ATTR_ALLOW_REVERSE,
    ATTR_ENTITY_ID,
    ATTR_KIND,
    ATTR_NAME,
    ATTR_ROOM_HINT,
    CONF_BLOCKLIST_ENTITY_ID_PREFIXES,
    CONF_BLOCKLIST_INTEGRATIONS,
    CONF_RECONNECT_INTERVAL,
    DOMAIN,
    FORWARD_COOLDOWN_SECONDS,
    KIND_SENSOR,
    KIND_SWITCH,
    ORIGIN_HA,
    ORIGIN_P44,
    REVERSE_COOLDOWN_SECONDS,
    Plan44ConfigEntry,
)
from .device_templates import MSG_INPUT, MSG_SENSOR
from .plan44_client import Plan44Client
from .plan44_core.models import DeviceCommand
from .state_mapping import ha_state_to_core
from .store import ExportRecord, Plan44Store

# Callback invoked with the latest value P44 pushed for an inbound channel.
InboundChannelCallback = Callable[[float], None]

# P44 message types that carry an inbound channel value, keyed for dispatch.
_INBOUND_MESSAGE_TYPES = (MSG_SENSOR, MSG_INPUT)

_LOGGER = logging.getLogger(__name__)

MAX_RECONNECT_ATTEMPTS = 10
MAX_RECONNECT_DELAY_SECONDS = 300

# plan44 push event types for physical device state changes.
# After subscribing, the bridge sends push messages for each event type when the
# corresponding device state changes — same inner structure as the HTTP poll.
_PUSH_EVENT_CHANNEL_STATES = "channelStates"
_PUSH_EVENT_SENSOR_STATES = "sensorStates"
_PUSH_EVENT_BINARY_INPUT_STATES = "binaryInputStates"


class Plan44Coordinator:
    def __init__(
        self,
        hass: HomeAssistant,
        entry: Plan44ConfigEntry,
        client: Plan44Client,
        store: Plan44Store,
        reverse_enabled: bool,
        auto_republish: bool,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.client = client
        self.store = store
        self.reverse_enabled = reverse_enabled
        self.auto_republish = auto_republish

        self._tracked_unsubs: list[Callable[[], None]] = []
        self._last_origin_by_entity: dict[str, str] = {}
        self._last_write_ts_by_entity: dict[str, float] = {}
        self._reconnect_task: asyncio.Task[None] | None = None
        self._startup_sync_unsub: Callable[[], None] | None = None
        # (message_type, tag, index) → callback for channels pushed by P44 into HA
        self._inbound_callbacks: dict[tuple[str, str, int], InboundChannelCallback] = {}
        # tag → set of channel indices seen from P44 but not yet imported
        self._discovered_indices_by_tag: dict[str, set[int]] = {}
        # Coordinator for dSUID-based device polling — receives push notifications
        self._device_coordinator: Plan44DeviceCoordinator | None = None

        reconnect_value = entry.options.get(
            CONF_RECONNECT_INTERVAL,
            entry.data[CONF_RECONNECT_INTERVAL],
        )
        self._reconnect_interval = int(cast(int, reconnect_value))
        blocked_integrations = entry.options.get(
            CONF_BLOCKLIST_INTEGRATIONS,
            entry.data.get(CONF_BLOCKLIST_INTEGRATIONS, ""),
        )
        blocked_prefixes = entry.options.get(
            CONF_BLOCKLIST_ENTITY_ID_PREFIXES,
            entry.data.get(CONF_BLOCKLIST_ENTITY_ID_PREFIXES, ""),
        )
        self._blocked_integrations = self._parse_csv(
            cast(str | list[str], blocked_integrations),
        )
        self._blocked_entity_prefixes = self._parse_csv(
            cast(str | list[str], blocked_prefixes),
        )

    def set_device_coordinator(self, dc: Plan44DeviceCoordinator) -> None:
        """Attach the device coordinator so push notifications can be routed to it."""
        self._device_coordinator = dc

    async def _async_subscribe_push(self) -> None:
        """Subscribe to plan44 push events for all physical device state changes."""
        try:
            await self.client.async_send(
                {
                    "message": "subscribe",
                    "events": [
                        _PUSH_EVENT_CHANNEL_STATES,
                        _PUSH_EVENT_SENSOR_STATES,
                        _PUSH_EVENT_BINARY_INPUT_STATES,
                    ],
                }
            )
            _LOGGER.debug(
                "Subscribed to plan44 push events (channel/sensor/input states)"
            )
        except Exception:
            _LOGGER.warning(
                "plan44: could not subscribe to push events; "
                "device state updates will rely on polling only"
            )

    async def async_initialize(self) -> None:
        self._refresh_exports()
        await self.client.async_connect()
        await self._async_subscribe_push()
        self._install_state_listener()
        if self.auto_republish:
            if self.hass.is_running:
                await self.async_republish_virtual_devices()
            else:

                @callback
                def _on_started(_event: Event[Any]) -> None:
                    self._startup_sync_unsub = None
                    self.hass.async_create_task(self.async_republish_virtual_devices())

                self._startup_sync_unsub = self.hass.bus.async_listen_once(
                    EVENT_HOMEASSISTANT_STARTED,
                    _on_started,
                )

    async def async_shutdown(self) -> None:
        for unsub in self._tracked_unsubs:
            unsub()
        self._tracked_unsubs.clear()

        startup_sync_unsub = self._startup_sync_unsub
        if startup_sync_unsub is not None:
            startup_sync_unsub()
            self._startup_sync_unsub = None

        reconnect_task = self._reconnect_task
        if reconnect_task is not None:
            reconnect_task.cancel()
            self._reconnect_task = None

        await self.client.async_disconnect()

    async def async_handle_disconnect(self) -> None:
        reconnect_task = self._reconnect_task
        if reconnect_task is not None and not reconnect_task.done():
            return
        self._reconnect_task = self.hass.async_create_task(self._async_reconnect_loop())

    async def _async_reconnect_loop(self) -> None:
        delay = max(1, self._reconnect_interval)
        for attempt in range(1, MAX_RECONNECT_ATTEMPTS + 1):
            try:
                await self.client.async_connect()
                await self._async_subscribe_push()
                if self.auto_republish:
                    await self.async_republish_virtual_devices()
                _LOGGER.info(
                    "Reconnected to plan44 on attempt %s/%s",
                    attempt,
                    MAX_RECONNECT_ATTEMPTS,
                )
                return
            except asyncio.CancelledError:
                raise
            except Exception as err:
                if attempt >= MAX_RECONNECT_ATTEMPTS:
                    _LOGGER.error(
                        "Failed to reconnect to plan44 after %s attempts: %s",
                        MAX_RECONNECT_ATTEMPTS,
                        err,
                    )
                    return

                _LOGGER.warning(
                    "Reconnect to plan44 failed on attempt %s/%s: %s. "
                    "Retrying in %s seconds",
                    attempt,
                    MAX_RECONNECT_ATTEMPTS,
                    err,
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, MAX_RECONNECT_DELAY_SECONDS)

    def _install_state_listener(self) -> None:
        tracked = list(self._exports_by_entity)
        if not tracked:
            return

        @callback
        def _on_state_change(event: Event[Any]) -> None:
            event_data = event.data
            entity_id = None
            if isinstance(event_data, Mapping):
                raw_entity_id = event_data.get("entity_id")
                if isinstance(raw_entity_id, str):
                    entity_id = raw_entity_id
            if entity_id is None:
                return
            self.hass.async_create_task(self.async_forward_entity_state(entity_id))

        self._tracked_unsubs.append(
            async_track_state_change_event(self.hass, tracked, _on_state_change)
        )

    async def async_reinstall_listener(self) -> None:
        for unsub in self._tracked_unsubs:
            unsub()
        self._tracked_unsubs.clear()
        self._install_state_listener()

    def _refresh_exports(self) -> None:
        exports: dict[str, ExportRecord] = {}
        for entity_id, cfg in self.store.iter_exports():
            exports[entity_id] = cfg
        for entity_id, cfg in self._iter_subentry_exports().items():
            exports[entity_id] = cfg
        self._exports_by_entity = exports
        self._entity_by_uid = {
            cfg["uid"]: entity_id for entity_id, cfg in exports.items()
        }

    def _iter_subentry_exports(self) -> dict[str, ExportRecord]:
        exports: dict[str, ExportRecord] = {}
        for subentry in getattr(self.entry, "subentries", {}).values():
            data = getattr(subentry, "data", None)
            if not isinstance(data, Mapping):
                continue
            entity_id = data.get(ATTR_ENTITY_ID)
            kind = data.get(ATTR_KIND)
            if not isinstance(entity_id, str) or not isinstance(kind, str):
                continue
            name = data.get(ATTR_NAME)
            room_hint = data.get(ATTR_ROOM_HINT)
            allow_reverse = data.get(ATTR_ALLOW_REVERSE, True)
            exports[entity_id] = {
                "uid": f"ha::{entity_id}",
                "kind": kind,
                "name": name if isinstance(name, str) and name else entity_id,
                "room_hint": room_hint if isinstance(room_hint, str) else None,
                "allow_reverse": bool(allow_reverse),
                "enabled": True,
                "source_domain": None,
            }
        return exports

    async def async_sync_runtime_exports(self) -> None:
        """Refresh runtime exports without tearing down the P44 connection."""
        previous_exports = dict(getattr(self, "_exports_by_entity", {}))
        self._refresh_exports()
        await self.async_reinstall_listener()

        added_or_changed: list[tuple[str, ExportRecord]] = []
        for entity_id, cfg in self._exports_by_entity.items():
            if previous_exports.get(entity_id) != cfg:
                added_or_changed.append((entity_id, cfg))

        if not added_or_changed:
            return

        await self.client.async_ensure_connected()
        for entity_id, cfg in added_or_changed:
            state = self.hass.states.get(entity_id)
            if state is None:
                continue
            unit_attr = state.attributes.get("unit_of_measurement")
            unit = unit_attr if isinstance(unit_attr, str) else None
            await self.client.async_register_device(
                cfg["uid"],
                cfg["name"],
                cfg["kind"],
                unit,
            )
            await self.async_forward_entity_state(entity_id, force=True)

    async def async_handle_subentry_removed(self) -> None:
        """Refresh runtime bookkeeping after subentry removal.

        P44 external devices don't support clean in-place removal, so we keep the
        active socket and only stop tracking removed entities locally. Existing
        remote devices will disappear on the next reconnect or restart.
        """
        self._refresh_exports()
        await self.async_reinstall_listener()

    async def async_create_virtual_device(
        self,
        entity_id: str,
        kind: str,
        name: str | None,
        room_hint: str | None,
        allow_reverse: bool,
    ) -> None:
        state = self.hass.states.get(entity_id)
        if state is None:
            raise HomeAssistantError(f"Unknown entity: {entity_id}")

        await self._async_validate_export(entity_id, kind)

        uid = f"ha::{entity_id}"
        display_name = name or state.name or entity_id
        source_domain = await self._async_get_entity_platform(entity_id)
        unit_attr = state.attributes.get("unit_of_measurement")
        unit = unit_attr if isinstance(unit_attr, str) else None

        await self.client.async_ensure_connected()
        await self.client.async_register_device(uid, display_name, kind, unit)
        await self.store.async_add_export(
            entity_id=entity_id,
            uid=uid,
            kind=kind,
            name=display_name,
            room_hint=room_hint,
            allow_reverse=allow_reverse,
            source_domain=source_domain,
        )
        self._refresh_exports()
        await self.async_reinstall_listener()
        await self.async_forward_entity_state(entity_id, force=True)

    async def async_remove_virtual_device(self, entity_id: str) -> None:
        await self.store.async_remove_export(entity_id)
        self._refresh_exports()
        await self.async_reinstall_listener()

    async def async_republish_virtual_devices(self) -> None:
        await self.client.async_ensure_connected()

        self._refresh_exports()
        for entity_id, cfg in self._exports_by_entity.items():
            state = self.hass.states.get(entity_id)
            if state is None:
                continue

            unit_attr = state.attributes.get("unit_of_measurement")
            unit = unit_attr if isinstance(unit_attr, str) else None
            await self.client.async_register_device(
                cfg["uid"],
                cfg["name"],
                cfg["kind"],
                unit,
            )
            await self.async_forward_entity_state(entity_id, force=True)

    # ------------------------------------------------------------------
    # Inbound channel callback registry (P44 physical device → HA entities)
    #
    # Physical devices already exist on plan44, so HA never registers them —
    # it only listens for the sensor/input values plan44 pushes.
    # ------------------------------------------------------------------

    def register_inbound_callback(
        self,
        message: str,
        tag: str,
        index: int,
        callback: InboundChannelCallback,
    ) -> None:
        """Register a callback for a P44-pushed channel value.

        message is the P44 message type ("sensor" or "input"); tag is the
        plan44 device id; index selects the channel.
        """
        self._inbound_callbacks[(message, tag, index)] = callback

    def unregister_inbound_callback(self, message: str, tag: str, index: int) -> None:
        """Remove the callback for a specific (message, tag, index) tuple."""
        self._inbound_callbacks.pop((message, tag, index), None)

    async def async_forward_entity_state(
        self,
        entity_id: str,
        force: bool = False,
    ) -> None:
        cfg = self._exports_by_entity.get(entity_id)
        if cfg is None or not cfg["enabled"]:
            return

        state = self.hass.states.get(entity_id)
        if state is None:
            return

        now = time.monotonic()
        last_origin = self._last_origin_by_entity.get(entity_id)
        last_ts = self._last_write_ts_by_entity.get(entity_id, 0.0)

        if (
            not force
            and last_origin == ORIGIN_P44
            and (now - last_ts) < FORWARD_COOLDOWN_SECONDS
        ):
            return

        await self.client.async_ensure_connected()

        core_state = ha_state_to_core(cfg["kind"], state)
        if core_state is None:
            return  # Skip forwarding if state conversion failed
        await self.client.async_push_state_messages(cfg["uid"], core_state)

        self._last_origin_by_entity[entity_id] = ORIGIN_HA
        self._last_write_ts_by_entity[entity_id] = now

    async def async_handle_plan44_message(self, msg: dict[str, Any]) -> None:
        # dSUID-based messages come from physical devices (e.g. Hue lights via the
        # plan44 bridge).  Route channelStates notifications to the device coordinator;
        # log anything else at debug level so we can identify new message types.
        dsuid_raw = msg.get("dSUID")
        if dsuid_raw is not None:
            msg_type = msg.get("message")
            if msg_type == _PUSH_EVENT_CHANNEL_STATES:
                if self._device_coordinator is not None:
                    self._device_coordinator.async_apply_push_channel_states(
                        str(dsuid_raw), msg
                    )
            elif msg_type in (
                _PUSH_EVENT_SENSOR_STATES,
                _PUSH_EVENT_BINARY_INPUT_STATES,
            ):
                if self._device_coordinator is not None:
                    self._device_coordinator.async_apply_push_sensor_states(
                        str(dsuid_raw), msg
                    )
            else:
                _LOGGER.debug(
                    "plan44 rx dSUID message (type=%r keys=%s)",
                    msg_type,
                    list(msg.keys()),
                )
            return

        tag_raw = msg.get("tag")
        if tag_raw is None:
            return

        tag = str(tag_raw)

        # Dispatch inbound channel messages (P44 physical device → HA entity)
        if msg.get("message") in _INBOUND_MESSAGE_TYPES:
            self.dispatch_inbound_channel(msg, tag)

        # Reverse control for exported virtual devices (P44 → HA service calls)
        entity_id = self._entity_by_uid.get(tag)
        if entity_id is None:
            return
        cfg = self._exports_by_entity.get(entity_id)
        if cfg is None:
            return

        if not self.reverse_enabled or not cfg["allow_reverse"]:
            return

        command = self.client.parse_message_as_command(msg, cfg["kind"])
        if command is None:
            return

        await self.async_apply_reverse_command(entity_id, cfg["kind"], command)

    async def async_apply_reverse_command(
        self,
        entity_id: str,
        kind: str,
        command: DeviceCommand,
    ) -> None:
        now = time.monotonic()
        last_origin = self._last_origin_by_entity.get(entity_id)
        last_ts = self._last_write_ts_by_entity.get(entity_id, 0.0)

        if last_origin == ORIGIN_HA and (now - last_ts) < REVERSE_COOLDOWN_SECONDS:
            return

        service_data: dict[str, Any] = {"entity_id": entity_id}

        if kind == KIND_SWITCH:
            domain = "switch"
            service = command.action
        else:
            domain = "light"
            if command.action == "turn_off":
                service = "turn_off"
            else:
                service = "turn_on"
                if command.value is not None:
                    service_data[ATTR_BRIGHTNESS] = int(command.value)

        await self.hass.services.async_call(
            domain,
            service,
            service_data,
            blocking=True,
        )

        self._last_origin_by_entity[entity_id] = ORIGIN_P44
        self._last_write_ts_by_entity[entity_id] = now

    async def _async_validate_export(self, entity_id: str, kind: str) -> None:
        state = self.hass.states.get(entity_id)
        if state is None:
            raise HomeAssistantError(f"Entity not found: {entity_id}")

        entity_domain = entity_id.split(".", 1)[0]
        if entity_domain != kind:
            raise HomeAssistantError(
                f"Entity domain '{entity_domain}' does not match "
                f"requested kind '{kind}'"
            )

        for prefix in self._blocked_entity_prefixes:
            if entity_id.startswith(prefix):
                raise HomeAssistantError(
                    f"Entity '{entity_id}' blocked by prefix rule '{prefix}'"
                )

        source_platform = await self._async_get_entity_platform(entity_id)
        # Loop guard: an entity provided by plan44 itself (imported from the
        # bridge) must not be exported back — that is a direct circular
        # reference (P44 -> HA -> P44).  This is enforced unconditionally,
        # independent of the configurable blocklist.
        if source_platform == DOMAIN:
            raise HomeAssistantError(
                f"Entity '{entity_id}' is provided by plan44 itself; exporting "
                f"it back would create a loop (circular reference)"
            )
        if source_platform and source_platform.lower() in self._blocked_integrations:
            raise HomeAssistantError(
                f"Entity '{entity_id}' originates from blocked integration "
                f"'{source_platform}'"
            )

        if kind == KIND_SENSOR:
            try:
                float(state.state)
            except (ValueError, TypeError) as err:
                raise HomeAssistantError(
                    f"Sensor entity '{entity_id}' has no numeric state"
                ) from err

    async def _async_get_entity_platform(self, entity_id: str) -> str | None:
        entity_registry = async_get_entity_registry(self.hass)
        entry = entity_registry.async_get(entity_id)
        if entry is None:
            return None
        return entry.platform

    def dispatch_inbound_channel(self, msg: dict[str, Any], tag: str) -> None:
        """Fire the registered callback when P44 pushes a sensor/input value.

        If no entity is listening for this (message, tag, index) yet, raise a
        persistent HA notification so the user can import the device as a
        'Plan44 device' subentry — without reinstalling the integration.
        """
        message = str(msg.get("message"))
        value_raw = msg.get("value")
        if value_raw is None:
            return
        try:
            value = float(value_raw)
        except ValueError, TypeError:
            _LOGGER.warning(
                "plan44 sent an invalid %s value for tag '%s': %s",
                message,
                tag,
                value_raw,
            )
            return
        index = int(msg.get("index", 0))
        cb = self._inbound_callbacks.get((message, tag, index))
        if cb is not None:
            cb(value)
        else:
            self._notify_discovered_channel(tag, index)

    def _notify_discovered_channel(self, tag: str, index: int) -> None:
        """Notify the user that P44 is pushing data for an unimported device.

        Indices seen for a tag are accumulated so the notification can hint at
        which template fits.  HA dedupes by notification_id, so repeated pushes
        just refresh the existing notification.
        """
        seen = self._discovered_indices_by_tag.setdefault(tag, set())
        seen.add(index)
        indices = ", ".join(str(i) for i in sorted(seen))
        notification_id = f"{DOMAIN}_{self.entry.entry_id}_discovery_{tag}"
        title = "plan44: Neues Gerät erkannt"
        message = (
            f"plan44 sendet Daten für ein noch nicht importiertes Gerät:\n\n"
            f"- **Tag:** `{tag}`\n"
            f"- **Bisher gesehene Kanäle (Index):** `{indices}`\n\n"
            f"Importiere es unter *Einstellungen → Geräte & Dienste → plan44* "
            f"über **+ Plan44-Gerät importieren**: gib diesen Tag ein und wähle das "
            f"passende Geräteprofil. Alle Kanäle werden dann automatisch als "
            f"Entitäten angelegt."
        )
        persistent_notification.async_create(
            hass=self.hass,
            message=message,
            title=title,
            notification_id=notification_id,
        )
        _LOGGER.info(
            "Discovered unimported plan44 device — tag=%s seen indices=%s",
            tag,
            indices,
        )

    @staticmethod
    def _parse_csv(value: str | list[str]) -> set[str]:
        if isinstance(value, list):
            return {item.strip().lower() for item in value if item.strip()}
        return {item.strip().lower() for item in value.split(",") if item.strip()}
