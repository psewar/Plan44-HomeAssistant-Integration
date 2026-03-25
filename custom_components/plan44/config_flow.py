from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigSubentry, ConfigSubentryFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.selector import selector

from .const import (
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
    DEFAULT_PORT,
    DEFAULT_RECONNECT_INTERVAL,
    DEFAULT_REVERSE_ENABLED,
    DEFAULT_VDC_MODEL_NAME,
    DOMAIN,
    KIND_SWITCH,
    SUBENTRY_TYPE_VIRTUAL_DEVICE,
    SUPPORTED_KINDS,
)
from .plan44_client import Plan44Client

ConfigDict = dict[str, Any]


async def _validate_connection(host: str, port: int, model: str) -> None:
    async def _noop_incoming(_: dict[str, Any]) -> None:
        return

    async def _noop_disconnect() -> None:
        return

    client = Plan44Client(
        host=host,
        port=port,
        vdc_model_name=model,
        incoming_callback=_noop_incoming,
        disconnect_callback=_noop_disconnect,
    )
    await client.async_connect()
    await asyncio.sleep(0)
    await client.async_disconnect()


def _options_schema(user_input: ConfigDict | None = None) -> vol.Schema:
    current = user_input or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_AUTO_REPUBLISH,
                default=current.get(CONF_AUTO_REPUBLISH, DEFAULT_AUTO_REPUBLISH),
            ): bool,
            vol.Required(
                CONF_REVERSE_ENABLED,
                default=current.get(CONF_REVERSE_ENABLED, DEFAULT_REVERSE_ENABLED),
            ): bool,
            vol.Required(
                CONF_RECONNECT_INTERVAL,
                default=current.get(
                    CONF_RECONNECT_INTERVAL,
                    DEFAULT_RECONNECT_INTERVAL,
                ),
            ): int,
            vol.Optional(
                CONF_BLOCKLIST_INTEGRATIONS,
                default=current.get(
                    CONF_BLOCKLIST_INTEGRATIONS,
                    DEFAULT_BLOCKLIST_INTEGRATIONS,
                ),
            ): str,
            vol.Optional(
                CONF_BLOCKLIST_ENTITY_ID_PREFIXES,
                default=current.get(
                    CONF_BLOCKLIST_ENTITY_ID_PREFIXES,
                    DEFAULT_BLOCKLIST_ENTITY_ID_PREFIXES,
                ),
            ): str,
        }
    )


def _virtual_device_kind_schema(current: ConfigDict | None = None) -> vol.Schema:
    current = current or {}
    return vol.Schema(
        {
            vol.Required(
                "kind",
                default=current.get("kind", KIND_SWITCH),
            ): selector(
                {
                    "select": {
                        "options": sorted(SUPPORTED_KINDS),
                        "mode": "dropdown",
                    }
                }
            ),
        }
    )


def _virtual_device_details_schema(
    kind: str,
    current: ConfigDict | None = None,
) -> vol.Schema:
    current = current or {}
    return vol.Schema(
        {
            vol.Required(
                "entity_id",
                default=current.get("entity_id", ""),
            ): selector(
                {
                    "entity": {
                        "multiple": False,
                        "filter": [{"domain": kind}],
                    }
                }
            ),
            vol.Optional(
                "name",
                default=current.get("name", ""),
            ): selector({"text": {}}),
            vol.Optional(
                "room_hint",
                default=current.get("room_hint", ""),
            ): selector({"text": {}}),
            vol.Optional(
                "allow_reverse",
                default=current.get("allow_reverse", True),
            ): selector({"boolean": {}}),
        }
    )


def _validate_virtual_device(
    hass: HomeAssistant,
    entry: ConfigEntry,
    user_input: ConfigDict,
    exclude_entity_id: str | None = None,
) -> dict[str, str]:
    errors: dict[str, str] = {}
    entity_id = user_input["entity_id"]
    kind = user_input["kind"]

    state = hass.states.get(entity_id)
    if state is None:
        errors["base"] = "entity_not_found"
        return errors

    entity_domain = entity_id.split(".", 1)[0]
    if entity_domain != kind:
        errors["base"] = "kind_mismatch"
        return errors

    for subentry in getattr(entry, "subentries", {}).values():
        data = getattr(subentry, "data", None)
        if not isinstance(data, dict):
            continue
        existing = data.get("entity_id")
        if existing == entity_id and entity_id != exclude_entity_id:
            errors["base"] = "already_configured"
            return errors

    if kind == "sensor":
        try:
            float(state.state)
        except TypeError, ValueError:
            errors["base"] = "sensor_not_numeric"

    return errors


async def _async_schedule_runtime_sync(
    hass: HomeAssistant,
    entry_id: str,
    removal: bool = False,
) -> None:
    await asyncio.sleep(0.2)
    entry = next(
        (
            config_entry
            for config_entry in hass.config_entries.async_entries(DOMAIN)
            if config_entry.entry_id == entry_id
        ),
        None,
    )
    if entry is None or not hasattr(entry, "runtime_data"):
        return
    coordinator = entry.runtime_data.coordinator
    if removal:
        await coordinator.async_handle_subentry_removed()
    else:
        await coordinator.async_sync_runtime_exports()


def _update_subentry_runtime(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry: ConfigSubentry,
    data: ConfigDict,
    title: str,
) -> None:
    hass.config_entries.async_update_subentry(
        entry,
        subentry,
        data=data,
        title=title,
    )
    hass.async_create_task(_async_schedule_runtime_sync(hass, entry.entry_id))


class Plan44ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self,
        user_input: ConfigDict | None = None,
    ) -> Any:
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _validate_connection(
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    user_input[CONF_VDC_MODEL_NAME],
                )
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                host = user_input[CONF_HOST]
                port = user_input[CONF_PORT]
                await self.async_set_unique_id(f"{host}:{port}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"plan44 ({host})",
                    data=user_input,
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Required(
                    CONF_VDC_MODEL_NAME,
                    default=DEFAULT_VDC_MODEL_NAME,
                ): str,
                vol.Required(
                    CONF_AUTO_REPUBLISH,
                    default=DEFAULT_AUTO_REPUBLISH,
                ): bool,
                vol.Required(
                    CONF_REVERSE_ENABLED,
                    default=DEFAULT_REVERSE_ENABLED,
                ): bool,
                vol.Required(
                    CONF_RECONNECT_INTERVAL,
                    default=DEFAULT_RECONNECT_INTERVAL,
                ): int,
                vol.Optional(
                    CONF_BLOCKLIST_INTEGRATIONS,
                    default=DEFAULT_BLOCKLIST_INTEGRATIONS,
                ): str,
                vol.Optional(
                    CONF_BLOCKLIST_ENTITY_ID_PREFIXES,
                    default=DEFAULT_BLOCKLIST_ENTITY_ID_PREFIXES,
                ): str,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: ConfigDict | None = None,
    ) -> Any:
        errors: dict[str, str] = {}
        entry = self._get_reconfigure_entry()

        if user_input is not None:
            try:
                await _validate_connection(
                    user_input[CONF_HOST],
                    user_input[CONF_PORT],
                    user_input[CONF_VDC_MODEL_NAME],
                )
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={
                        **entry.data,
                        CONF_HOST: user_input[CONF_HOST],
                        CONF_PORT: user_input[CONF_PORT],
                        CONF_VDC_MODEL_NAME: user_input[CONF_VDC_MODEL_NAME],
                    },
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                vol.Required(CONF_PORT, default=entry.data[CONF_PORT]): int,
                vol.Required(
                    CONF_VDC_MODEL_NAME,
                    default=entry.data[CONF_VDC_MODEL_NAME],
                ): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls,
        config_entry: ConfigEntry,
    ) -> dict[str, type[ConfigSubentryFlow]]:
        del config_entry
        return {SUBENTRY_TYPE_VIRTUAL_DEVICE: Plan44VirtualDeviceSubentryFlow}

    @staticmethod
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> Plan44OptionsFlow:
        return Plan44OptionsFlow(config_entry)


class Plan44OptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self,
        user_input: ConfigDict | None = None,
    ) -> Any:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current: ConfigDict = {
            **dict(self._config_entry.data),
            **dict(self._config_entry.options),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(current),
        )


class Plan44VirtualDeviceSubentryFlow(config_entries.ConfigSubentryFlow):
    def __init__(self) -> None:
        self._selected_kind: str | None = None

    async def async_step_user(
        self,
        user_input: ConfigDict | None = None,
    ) -> Any:
        if user_input is not None:
            self._selected_kind = user_input["kind"]
            return await self.async_step_details()

        current: ConfigDict = {}
        if self._selected_kind is not None:
            current["kind"] = self._selected_kind
        return self.async_show_form(
            step_id="user",
            data_schema=_virtual_device_kind_schema(current),
            errors={},
        )

    async def async_step_details(
        self,
        user_input: ConfigDict | None = None,
    ) -> Any:
        entry = self._get_entry()
        errors: dict[str, str] = {}
        kind = self._selected_kind or KIND_SWITCH

        if user_input is not None:
            payload = {**user_input, "kind": kind}
            errors = _validate_virtual_device(
                self.hass,
                entry,
                payload,
            )
            if not errors:
                entity_id = payload["entity_id"]
                name = payload.get("name") or entity_id
                self.hass.async_create_task(
                    _async_schedule_runtime_sync(self.hass, entry.entry_id)
                )
                return self.async_create_entry(title=name, data=payload)

        current: ConfigDict = {"kind": kind}
        if user_input is not None:
            current.update(user_input)
        return self.async_show_form(
            step_id="details",
            data_schema=_virtual_device_details_schema(kind, current),
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        user_input: ConfigDict | None = None,
    ) -> Any:
        entry = self._get_entry()
        subentry = self._get_reconfigure_subentry()
        current = dict(getattr(subentry, "data", {}))
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_virtual_device(
                self.hass,
                entry,
                user_input,
                exclude_entity_id=current.get("entity_id"),
            )
            if not errors:
                name = user_input.get("name") or user_input["entity_id"]
                _update_subentry_runtime(
                    self.hass,
                    entry,
                    subentry,
                    user_input,
                    name,
                )
                return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_virtual_device_details_schema(
                current.get("kind", KIND_SWITCH),
                current,
            ),
            errors=errors,
        )
