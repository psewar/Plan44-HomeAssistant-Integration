from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigSubentry, ConfigSubentryFlow
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import selector

from .const import (
    ATTR_CHANNELS,
    ATTR_DEVICE_CLASS,
    ATTR_DSUID,
    ATTR_MODEL,
    ATTR_NAME,
    ATTR_P44_INDEX,
    ATTR_P44_TAG,
    ATTR_PLATFORM,
    ATTR_TEMPLATE,
    ATTR_UNIT,
    CONF_AUTO_REPUBLISH,
    CONF_BLOCKLIST_ENTITY_ID_PREFIXES,
    CONF_BLOCKLIST_INTEGRATIONS,
    CONF_HOST,
    CONF_PORT,
    CONF_RECONNECT_INTERVAL,
    CONF_REVERSE_ENABLED,
    CONF_VDC_MODEL_NAME,
    CONF_VERIFY_SSL,
    CONF_WEB_CERT,
    CONF_WEB_PASSWORD,
    CONF_WEB_POLL_INTERVAL,
    CONF_WEB_USER,
    DEFAULT_AUTO_REPUBLISH,
    DEFAULT_BLOCKLIST_ENTITY_ID_PREFIXES,
    DEFAULT_BLOCKLIST_INTEGRATIONS,
    DEFAULT_PORT,
    DEFAULT_RECONNECT_INTERVAL,
    DEFAULT_REVERSE_ENABLED,
    DEFAULT_VDC_MODEL_NAME,
    DEFAULT_VERIFY_SSL,
    DEFAULT_WEB_POLL_INTERVAL,
    DOMAIN,
    KIND_BINARY_SENSOR,
    KIND_LIGHT,
    KIND_SENSOR,
    KIND_SWITCH,
    SUBENTRY_TYPE_P44_DEVICE,
    SUBENTRY_TYPE_VIRTUAL_DEVICE,
    SUPPORTED_KINDS,
)
from .device_templates import (
    PLATFORM_BINARY_SENSOR,
    PLATFORM_SENSOR,
    TEMPLATE_CUSTOM,
    template_options,
)
from .plan44_client import Plan44Client
from .web_client import (
    DiscoveredDevice,
    Plan44WebApi,
    Plan44WebApiError,
    default_web_url,
)

_LOGGER = logging.getLogger(__name__)

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


def _as_list(value: Any) -> list[str]:
    """Normalise a stored blocklist value (CSV string or list) to a list."""
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def _integration_select(hass: HomeAssistant, current_value: Any) -> Any:
    """A multi-select of the installed integration domains.

    ``custom_value`` keeps free-text entries allowed (e.g. integrations that
    aren't installed yet, or the digitalSTROM defaults on a fresh system), and
    the currently-selected values are always merged into the options so they
    still render as chips even when their integration isn't loaded.
    """
    selected = _as_list(current_value)
    domains = set(hass.config_entries.async_domains())
    options = sorted(domains | set(selected))
    return selector(
        {
            "select": {
                "options": options,
                "multiple": True,
                "custom_value": True,
                "mode": "dropdown",
                "sort": True,
            }
        }
    )


def _options_schema(
    hass: HomeAssistant,
    user_input: ConfigDict | None = None,
) -> vol.Schema:
    current = user_input or {}
    blocklist_integrations = current.get(
        CONF_BLOCKLIST_INTEGRATIONS,
        DEFAULT_BLOCKLIST_INTEGRATIONS,
    )
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
                default=_as_list(blocklist_integrations),
            ): _integration_select(hass, blocklist_integrations),
            vol.Optional(
                CONF_BLOCKLIST_ENTITY_ID_PREFIXES,
                default=current.get(
                    CONF_BLOCKLIST_ENTITY_ID_PREFIXES,
                    DEFAULT_BLOCKLIST_ENTITY_ID_PREFIXES,
                ),
            ): str,
            vol.Optional(
                CONF_WEB_USER,
                default=current.get(CONF_WEB_USER, ""),
            ): str,
            vol.Optional(
                CONF_WEB_PASSWORD,
                default=current.get(CONF_WEB_PASSWORD, ""),
            ): selector({"text": {"type": "password"}}),
            vol.Required(
                CONF_WEB_POLL_INTERVAL,
                default=current.get(CONF_WEB_POLL_INTERVAL, DEFAULT_WEB_POLL_INTERVAL),
            ): int,
            vol.Optional(
                CONF_VERIFY_SSL,
                default=current.get(CONF_VERIFY_SSL, DEFAULT_VERIFY_SSL),
            ): bool,
        }
    )


# The virtual-device type equals the source entity's domain, so the user just
# picks an entity (filtered to the supported domains) and the kind is derived.
_VIRTUAL_DEVICE_ENTITY_FILTER = [
    {"domain": KIND_SWITCH},
    {"domain": KIND_LIGHT},
    {"domain": KIND_SENSOR},
    {"domain": KIND_BINARY_SENSOR},
]


def _kind_from_entity_id(entity_id: str) -> str:
    """Derive the virtual-device kind from an entity id (kind == domain)."""
    return entity_id.split(".", 1)[0]


def _virtual_device_form_schema(current: ConfigDict | None = None) -> vol.Schema:
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
                        "filter": _VIRTUAL_DEVICE_ENTITY_FILTER,
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
    kind = _kind_from_entity_id(entity_id)

    state = hass.states.get(entity_id)
    if state is None:
        errors["base"] = "entity_not_found"
        return errors

    # Loop guard: an entity provided by plan44 itself (i.e. imported from the
    # bridge via a p44_device subentry) must not be exported back to plan44 —
    # that would be a direct circular reference (P44 -> HA -> P44).
    registry_entry = er.async_get(hass).async_get(entity_id)
    if registry_entry is not None and registry_entry.platform == DOMAIN:
        errors["base"] = "circular_reference"
        return errors

    if kind not in SUPPORTED_KINDS:
        errors["base"] = "unsupported_domain"
        return errors

    if kind == KIND_SENSOR:
        try:
            float(state.state)
        except ValueError, TypeError:
            errors["base"] = "sensor_not_numeric"
            return errors

    for subentry in getattr(entry, "subentries", {}).values():
        data = getattr(subentry, "data", None)
        if not isinstance(data, dict):
            continue
        existing = data.get("entity_id")
        if existing == entity_id and entity_id != exclude_entity_id:
            errors["base"] = "already_configured"
            return errors

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
                    default=_as_list(DEFAULT_BLOCKLIST_INTEGRATIONS),
                ): _integration_select(self.hass, DEFAULT_BLOCKLIST_INTEGRATIONS),
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
        return {
            SUBENTRY_TYPE_VIRTUAL_DEVICE: Plan44VirtualDeviceSubentryFlow,
            SUBENTRY_TYPE_P44_DEVICE: Plan44P44DeviceSubentryFlow,
        }

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
            # Reload so web-API config (and other options) take effect at once.
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self._config_entry.entry_id)
            )
            return self.async_create_entry(title="", data=user_input)

        current: ConfigDict = {
            **dict(self._config_entry.data),
            **dict(self._config_entry.options),
        }
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(self.hass, current),
        )


class Plan44VirtualDeviceSubentryFlow(config_entries.ConfigSubentryFlow):
    async def async_step_user(
        self,
        user_input: ConfigDict | None = None,
    ) -> Any:
        entry = self._get_entry()
        errors: dict[str, str] = {}

        if user_input is not None:
            errors = _validate_virtual_device(
                self.hass,
                entry,
                user_input,
            )
            if not errors:
                entity_id = user_input["entity_id"]
                name = user_input.get("name") or entity_id
                # The kind is derived from the entity domain and persisted so the
                # coordinator/export logic can read it.
                data = {**user_input, "kind": _kind_from_entity_id(entity_id)}
                self.hass.async_create_task(
                    _async_schedule_runtime_sync(self.hass, entry.entry_id)
                )
                return self.async_create_entry(title=name, data=data)

        current = user_input or {}
        return self.async_show_form(
            step_id="user",
            data_schema=_virtual_device_form_schema(current),
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
                data = {
                    **user_input,
                    "kind": _kind_from_entity_id(user_input["entity_id"]),
                }
                _update_subentry_runtime(
                    self.hass,
                    entry,
                    subentry,
                    data,
                    name,
                )
                return self.async_abort(reason="reconfigure_successful")

        current = user_input or current
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_virtual_device_form_schema(current),
            errors=errors,
        )


# ---------------------------------------------------------------------------
# P44 physical-device subentry flow (template-based import)
# ---------------------------------------------------------------------------


def _p44_device_form_schema(current: ConfigDict | None = None) -> vol.Schema:
    """Step 1: choose tag + device template + display name."""
    c = current or {}
    options = [
        {"value": key, "label": label} for key, label in template_options().items()
    ]
    return vol.Schema(
        {
            vol.Required(ATTR_P44_TAG, default=c.get(ATTR_P44_TAG, "")): selector(
                {"text": {}}
            ),
            vol.Required(
                ATTR_TEMPLATE,
                default=c.get(ATTR_TEMPLATE, next(iter(template_options()))),
            ): selector({"select": {"options": options, "mode": "dropdown"}}),
            vol.Optional(ATTR_NAME, default=c.get(ATTR_NAME, "")): selector(
                {"text": {}}
            ),
        }
    )


def _p44_custom_form_schema(current: ConfigDict | None = None) -> vol.Schema:
    """Step 2 (custom template only): single-channel details."""
    c = current or {}
    return vol.Schema(
        {
            vol.Optional(ATTR_P44_INDEX, default=c.get(ATTR_P44_INDEX, 0)): selector(
                {"number": {"min": 0, "max": 31, "mode": "box"}}
            ),
            vol.Required(
                ATTR_PLATFORM, default=c.get(ATTR_PLATFORM, PLATFORM_SENSOR)
            ): selector(
                {
                    "select": {
                        "options": [PLATFORM_SENSOR, PLATFORM_BINARY_SENSOR],
                        "mode": "dropdown",
                    }
                }
            ),
            vol.Optional(ATTR_UNIT, default=c.get(ATTR_UNIT, "")): selector(
                {"text": {}}
            ),
            vol.Optional(
                ATTR_DEVICE_CLASS, default=c.get(ATTR_DEVICE_CLASS, "")
            ): selector({"text": {}}),
        }
    )


def _p44_reconfigure_name_schema(current: ConfigDict | None = None) -> vol.Schema:
    """Reconfigure schema for picker-imported (dSUID) devices: display name only.

    Their identity (dSUID) and channels are read live from the bridge and must
    not be hand-edited, so the tag/profile fields of the manual form do not
    apply here — only the display name is offered.
    """
    c = current or {}
    return vol.Schema(
        {
            vol.Optional(ATTR_NAME, default=c.get(ATTR_NAME) or ""): selector(
                {"text": {}}
            ),
        }
    )


def _validate_p44_device(user_input: ConfigDict) -> dict[str, str]:
    errors: dict[str, str] = {}
    if not str(user_input.get(ATTR_P44_TAG, "")).strip():
        errors[ATTR_P44_TAG] = "p44_tag_required"
    return errors


async def _async_schedule_entry_reload(hass: HomeAssistant, entry_id: str) -> None:
    """Reload the config entry so the platforms pick up subentry changes."""
    await asyncio.sleep(0.3)
    await hass.config_entries.async_reload(entry_id)


def _serialize_device(device: DiscoveredDevice) -> ConfigDict:
    """Serialize a REST-discovered device into subentry data."""
    return {
        ATTR_DSUID: device.dsuid,
        ATTR_NAME: device.name,
        ATTR_MODEL: device.model,
        ATTR_CHANNELS: [
            {
                "key": c.key,
                "name": c.name,
                "platform": c.platform,
                "unit": c.unit,
                "device_class": c.device_class,
                "state_class": c.state_class,
            }
            for c in device.channels
        ],
    }


class Plan44P44DeviceSubentryFlow(config_entries.ConfigSubentryFlow):
    """Import a physical plan44 device into HA.

    When the bridge web API is configured, the user picks a real device from a
    live dropdown and its channels are derived automatically.  Otherwise it
    falls back to a manual tag + profile template form.
    """

    _pending: ConfigDict
    _discovered: dict[str, DiscoveredDevice]

    def _get_web_api(self) -> Plan44WebApi | None:
        entry = self._get_entry()
        api = getattr(getattr(entry, "runtime_data", None), "web_api", None)
        if api is not None:
            return api
        merged = {**entry.data, **entry.options}
        user = merged.get(CONF_WEB_USER)
        password = merged.get(CONF_WEB_PASSWORD)
        if not (user and password):
            return None
        url = default_web_url(merged.get(CONF_HOST))
        if not url:
            return None
        return Plan44WebApi(
            self.hass,
            str(url),
            str(user),
            str(password),
            pinned_cert=merged.get(CONF_WEB_CERT),
        )

    async def async_step_user(
        self,
        user_input: ConfigDict | None = None,
    ) -> Any:
        # Dispatcher: prefer the live device picker, else the manual form.
        if self._get_web_api() is not None:
            return await self.async_step_pick_device()
        return await self.async_step_manual(user_input)

    async def async_step_pick_device(
        self,
        user_input: ConfigDict | None = None,
    ) -> Any:
        web_api = self._get_web_api()
        if web_api is None:
            return await self.async_step_manual()

        if user_input is not None:
            device = getattr(self, "_discovered", {}).get(user_input[ATTR_DSUID])
            if device is not None:
                self.hass.async_create_task(
                    _async_schedule_entry_reload(self.hass, self._get_entry().entry_id)
                )
                return self.async_create_entry(
                    title=device.name, data=_serialize_device(device)
                )

        try:
            devices = await web_api.async_list_devices()
        except Plan44WebApiError as err:
            _LOGGER.warning("plan44 web API device list failed: %s", err)
            return await self.async_step_manual(web_error="web_api_unreachable")
        if not devices:
            return await self.async_step_manual(web_error="web_api_no_devices")

        self._discovered = {d.dsuid: d for d in devices}
        options = [
            {
                "value": d.dsuid,
                "label": f"{d.name} — {d.model}" if d.model else d.name,
            }
            for d in sorted(devices, key=lambda d: d.name.lower())
        ]
        schema = vol.Schema(
            {
                vol.Required(ATTR_DSUID): selector(
                    {"select": {"options": options, "mode": "dropdown"}}
                )
            }
        )
        return self.async_show_form(step_id="pick_device", data_schema=schema)

    async def async_step_manual(
        self,
        user_input: ConfigDict | None = None,
        web_error: str | None = None,
    ) -> Any:
        errors: dict[str, str] = {}
        if web_error:
            errors["base"] = web_error

        if user_input is not None:
            errors = _validate_p44_device(user_input)
            if not errors:
                base: ConfigDict = {
                    ATTR_P44_TAG: str(user_input[ATTR_P44_TAG]).strip(),
                    ATTR_TEMPLATE: user_input[ATTR_TEMPLATE],
                    ATTR_NAME: str(user_input.get(ATTR_NAME, "")).strip() or None,
                }
                if user_input[ATTR_TEMPLATE] == TEMPLATE_CUSTOM:
                    self._pending = base
                    return await self.async_step_custom()
                return self._create(base)

        return self.async_show_form(
            step_id="manual",
            data_schema=_p44_device_form_schema(user_input or {}),
            errors=errors,
        )

    async def async_step_custom(
        self,
        user_input: ConfigDict | None = None,
    ) -> Any:
        if user_input is not None:
            data = {
                **self._pending,
                ATTR_P44_INDEX: int(user_input.get(ATTR_P44_INDEX, 0)),
                ATTR_PLATFORM: user_input.get(ATTR_PLATFORM, PLATFORM_SENSOR),
                ATTR_UNIT: str(user_input.get(ATTR_UNIT, "")).strip() or None,
                ATTR_DEVICE_CLASS: str(user_input.get(ATTR_DEVICE_CLASS, "")).strip()
                or None,
            }
            return self._create(data)

        return self.async_show_form(
            step_id="custom",
            data_schema=_p44_custom_form_schema(),
        )

    def _create(self, data: ConfigDict) -> Any:
        name = data.get(ATTR_NAME) or data.get(ATTR_P44_TAG) or data.get(ATTR_DSUID)
        self.hass.async_create_task(
            _async_schedule_entry_reload(self.hass, self._get_entry().entry_id)
        )
        return self.async_create_entry(title=str(name), data=data)

    async def async_step_reconfigure(
        self,
        user_input: ConfigDict | None = None,
    ) -> Any:
        subentry = self._get_reconfigure_subentry()
        current = dict(getattr(subentry, "data", {}))

        # Picker-imported (dSUID) devices: identity and channels come from the
        # live bridge, so only the display name is editable.  Manual (tag +
        # template) devices keep the full form below.
        if current.get(ATTR_DSUID):
            return await self._async_reconfigure_dsuid_name(
                subentry, current, user_input
            )

        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_p44_device(user_input)
            if not errors:
                data = {
                    **current,
                    ATTR_P44_TAG: str(user_input[ATTR_P44_TAG]).strip(),
                    ATTR_TEMPLATE: user_input[ATTR_TEMPLATE],
                    ATTR_NAME: str(user_input.get(ATTR_NAME, "")).strip() or None,
                }
                name = data.get(ATTR_NAME) or data[ATTR_P44_TAG]
                entry = self._get_entry()
                self.hass.config_entries.async_update_subentry(
                    entry, subentry, data=data, title=str(name)
                )
                self.hass.async_create_task(
                    _async_schedule_entry_reload(self.hass, entry.entry_id)
                )
                return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_p44_device_form_schema(user_input or current),
            errors=errors,
        )

    async def _async_reconfigure_dsuid_name(
        self,
        subentry: ConfigSubentry,
        current: ConfigDict,
        user_input: ConfigDict | None,
    ) -> Any:
        """Reconfigure a picker-imported (dSUID) device: display name only."""
        if user_input is not None:
            name = str(user_input.get(ATTR_NAME, "")).strip() or None
            data = {**current, ATTR_NAME: name}
            title = name or str(current.get(ATTR_DSUID))
            entry = self._get_entry()
            self.hass.config_entries.async_update_subentry(
                entry, subentry, data=data, title=title
            )
            self.hass.async_create_task(
                _async_schedule_entry_reload(self.hass, entry.entry_id)
            )
            return self.async_abort(reason="reconfigure_successful")

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_p44_reconfigure_name_schema(current),
        )
