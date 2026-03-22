from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any, cast

from homeassistant.components.light import ATTR_BRIGHTNESS
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.event import async_track_state_change_event

from plan44_core.models import (
    BinarySensorState,
    DeviceCommand,
    DeviceState,
    LightState,
    SensorState,
    SwitchState,
)

from .const import (
    CONF_BLOCKLIST_ENTITY_ID_PREFIXES,
    CONF_BLOCKLIST_INTEGRATIONS,
    CONF_RECONNECT_INTERVAL,
    FORWARD_COOLDOWN_SECONDS,
    KIND_BINARY_SENSOR,
    KIND_LIGHT,
    KIND_SENSOR,
    KIND_SWITCH,
    ORIGIN_HA,
    ORIGIN_P44,
    REVERSE_COOLDOWN_SECONDS,
    Plan44ConfigEntry,
)
from .plan44_client import Plan44Client
from .store import Plan44Store

_LOGGER = logging.getLogger(__name__)


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

    async def async_initialize(self) -> None:
        await self.client.async_connect()
        if self.auto_republish:
            await self.async_republish_virtual_devices()
        self._install_state_listener()

    async def async_shutdown(self) -> None:
        for unsub in self._tracked_unsubs:
            unsub()
        self._tracked_unsubs.clear()

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
        while True:
            try:
                await self.client.async_connect()
                if self.auto_republish:
                    await self.async_republish_virtual_devices()
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("Reconnect to plan44 failed")
                await asyncio.sleep(self._reconnect_interval)

    def _install_state_listener(self) -> None:
        tracked = [entity_id for entity_id, _cfg in self.store.iter_exports()]
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
        await self.async_reinstall_listener()
        await self.async_forward_entity_state(entity_id, force=True)

    async def async_remove_virtual_device(self, entity_id: str) -> None:
        await self.store.async_remove_export(entity_id)
        await self.async_reinstall_listener()

    async def async_republish_virtual_devices(self) -> None:
        await self.client.async_ensure_connected()

        for entity_id, cfg in self.store.iter_exports():
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

    async def async_forward_entity_state(
        self,
        entity_id: str,
        force: bool = False,
    ) -> None:
        cfg = self.store.get_export(entity_id)
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

        core_state = self._state_to_core(cfg["kind"], state)
        await self.client.async_push_state_messages(cfg["uid"], core_state)

        self._last_origin_by_entity[entity_id] = ORIGIN_HA
        self._last_write_ts_by_entity[entity_id] = now

    async def async_handle_plan44_message(self, msg: dict[str, Any]) -> None:
        tag_raw = msg.get("tag")
        if tag_raw is None:
            return

        tag = str(tag_raw)
        entity_id, cfg = self.store.get_export_by_uid(tag)
        if entity_id is None or cfg is None:
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

    @staticmethod
    def _parse_csv(value: str | list[str]) -> set[str]:
        if isinstance(value, list):
            return {item.strip().lower() for item in value if item.strip()}
        return {item.strip().lower() for item in value.split(",") if item.strip()}

    @staticmethod
    def _state_to_core(kind: str, state: State) -> DeviceState:
        attributes = state.attributes

        if kind == KIND_SWITCH:
            return SwitchState(is_on=state.state.lower() == "on")
        if kind == KIND_LIGHT:
            brightness_attr = attributes.get(ATTR_BRIGHTNESS)
            brightness = (
                int(brightness_attr)
                if isinstance(brightness_attr, (int, float))
                else None
            )
            return LightState(
                is_on=state.state.lower() == "on",
                brightness=brightness,
            )
        if kind == KIND_BINARY_SENSOR:
            return BinarySensorState(is_on=state.state.lower() == "on")
        if kind == KIND_SENSOR:
            return SensorState(numeric_value=float(state.state))
        raise HomeAssistantError(f"Unsupported export kind: {kind}")
