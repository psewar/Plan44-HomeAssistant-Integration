from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

from homeassistant.components.light import ATTR_BRIGHTNESS
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    CONF_BLOCKLIST_ENTITY_ID_PREFIXES,
    CONF_BLOCKLIST_INTEGRATIONS,
    CONF_RECONNECT_INTERVAL,
    FORWARD_COOLDOWN_SECONDS,
    KIND_BINARY_SENSOR,
    KIND_LIGHT,
    KIND_SENSOR,
    KIND_SWITCH,
    LIGHT_MAX_BRIGHTNESS,
    LIGHT_ON_THRESHOLD,
    ORIGIN_HA,
    ORIGIN_P44,
    P44_MAX_CHANNEL_VALUE,
    REVERSE_COOLDOWN_SECONDS,
)
from .plan44_client import Plan44Client
from .store import Plan44Store

_LOGGER = logging.getLogger(__name__)


class Plan44Coordinator:
    def __init__(
        self,
        hass: HomeAssistant,
        entry,
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
        self._reconnect_task: asyncio.Task | None = None

        self._reconnect_interval = int(
            entry.options.get(CONF_RECONNECT_INTERVAL, entry.data[CONF_RECONNECT_INTERVAL])
        )
        self._blocked_integrations = self._parse_csv(
            entry.options.get(
                CONF_BLOCKLIST_INTEGRATIONS,
                entry.data.get(CONF_BLOCKLIST_INTEGRATIONS, ""),
            )
        )
        self._blocked_entity_prefixes = self._parse_csv(
            entry.options.get(
                CONF_BLOCKLIST_ENTITY_ID_PREFIXES,
                entry.data.get(CONF_BLOCKLIST_ENTITY_ID_PREFIXES, ""),
            )
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

        if self._reconnect_task:
            self._reconnect_task.cancel()
            self._reconnect_task = None

        await self.client.async_disconnect()

    async def async_handle_disconnect(self) -> None:
        if self._reconnect_task and not self._reconnect_task.done():
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
        def _on_state_change(event) -> None:
            entity_id = event.data.get("entity_id")
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

        await self.client.async_ensure_connected()
        await self._async_register_with_plan44(uid, display_name, kind, state.attributes)
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

            await self._async_register_with_plan44(
                cfg["uid"],
                cfg["name"],
                cfg["kind"],
                state.attributes,
            )
            await self.async_forward_entity_state(entity_id, force=True)

    async def async_forward_entity_state(self, entity_id: str, force: bool = False) -> None:
        cfg = self.store.get_export(entity_id)
        if not cfg or not cfg.get("enabled", True):
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

        kind = cfg["kind"]
        uid = cfg["uid"]

        if kind == KIND_SWITCH:
            value = 100 if state.state.lower() == "on" else 0
            await self.client.async_push_channel_value(uid, value)
        elif kind == KIND_LIGHT:
            value = self._light_state_to_p44_value(state)
            await self.client.async_push_channel_value(uid, value)
        elif kind == KIND_BINARY_SENSOR:
            value = 100 if state.state.lower() == "on" else 0
            await self.client.async_push_channel_value(uid, value)
        elif kind == KIND_SENSOR:
            try:
                sensor_value = float(state.state)
            except (TypeError, ValueError):
                return
            await self.client.async_push_sensor_value(uid, sensor_value)
        else:
            raise HomeAssistantError(f"Unsupported export kind: {kind}")

        self._last_origin_by_entity[entity_id] = ORIGIN_HA
        self._last_write_ts_by_entity[entity_id] = now

    async def async_handle_plan44_message(self, msg: dict) -> None:
        message_type = msg.get("message")
        tag = msg.get("tag")

        if message_type != "channel" or not tag:
            return

        entity_id, cfg = self.store.get_export_by_uid(tag)
        if not entity_id or not cfg:
            return

        if not self.reverse_enabled or not cfg.get("allow_reverse", True):
            return

        kind = cfg["kind"]
        value = msg.get("value", 0)

        if kind not in (KIND_SWITCH, KIND_LIGHT):
            return

        await self.async_apply_reverse_command(entity_id, kind, value)

    async def async_apply_reverse_command(self, entity_id: str, kind: str, value: int | float) -> None:
        now = time.monotonic()
        last_origin = self._last_origin_by_entity.get(entity_id)
        last_ts = self._last_write_ts_by_entity.get(entity_id, 0.0)

        if last_origin == ORIGIN_HA and (now - last_ts) < REVERSE_COOLDOWN_SECONDS:
            return

        service_data = {"entity_id": entity_id}

        if kind == KIND_SWITCH:
            domain = "switch"
            service = "turn_on" if float(value) > 0 else "turn_off"
        else:
            domain = "light"
            if float(value) > 0:
                service = "turn_on"
                service_data[ATTR_BRIGHTNESS] = self._p44_value_to_brightness(value)
            else:
                service = "turn_off"

        await self.hass.services.async_call(domain, service, service_data, blocking=True)

        self._last_origin_by_entity[entity_id] = ORIGIN_P44
        self._last_write_ts_by_entity[entity_id] = now

    async def _async_register_with_plan44(
        self,
        uid: str,
        name: str,
        kind: str,
        attributes: dict,
    ) -> None:
        if kind in (KIND_SWITCH, KIND_LIGHT, KIND_BINARY_SENSOR):
            await self.client.async_register_switch_like(uid, name)
            return

        if kind == KIND_SENSOR:
            unit = attributes.get("unit_of_measurement")
            await self.client.async_register_sensor(uid, name, unit)
            return

        raise HomeAssistantError(f"Unsupported kind: {kind}")

    async def _async_validate_export(self, entity_id: str, kind: str) -> None:
        state = self.hass.states.get(entity_id)
        if state is None:
            raise HomeAssistantError(f"Entity not found: {entity_id}")

        entity_domain = entity_id.split(".", 1)[0]
        if entity_domain != kind:
            raise HomeAssistantError(
                f"Entity domain '{entity_domain}' does not match requested kind '{kind}'"
            )

        for prefix in self._blocked_entity_prefixes:
            if entity_id.startswith(prefix):
                raise HomeAssistantError(
                    f"Entity '{entity_id}' blocked by prefix rule '{prefix}'"
                )

        source_platform = await self._async_get_entity_platform(entity_id)
        if source_platform and source_platform.lower() in self._blocked_integrations:
            raise HomeAssistantError(
                f"Entity '{entity_id}' originates from blocked integration '{source_platform}'"
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
            return {item.strip().lower() for item in value if item and item.strip()}
        return {item.strip().lower() for item in value.split(",") if item and item.strip()}

    @staticmethod
    def _light_state_to_p44_value(state) -> int:
        if state.state.lower() != "on":
            return 0

        brightness = state.attributes.get(ATTR_BRIGHTNESS)
        if brightness is None:
            return 100

        scaled = round((int(brightness) / LIGHT_MAX_BRIGHTNESS) * P44_MAX_CHANNEL_VALUE)
        return max(LIGHT_ON_THRESHOLD, min(P44_MAX_CHANNEL_VALUE, scaled))

    @staticmethod
    def _p44_value_to_brightness(value: int | float) -> int:
        value = max(0, min(P44_MAX_CHANNEL_VALUE, int(float(value))))
        if value == 0:
            return 0
        return max(1, round((value / P44_MAX_CHANNEL_VALUE) * LIGHT_MAX_BRIGHTNESS))
