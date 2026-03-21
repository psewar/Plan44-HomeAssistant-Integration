from __future__ import annotations

import asyncio

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

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
)
from .plan44_client import Plan44Client


async def _validate_connection(host: str, port: int, model: str) -> None:
    async def _noop_incoming(_: dict) -> None:
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


def _options_schema(user_input: dict | None = None) -> vol.Schema:
    user_input = user_input or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_AUTO_REPUBLISH,
                default=user_input.get(
                    CONF_AUTO_REPUBLISH,
                    DEFAULT_AUTO_REPUBLISH,
                ),
            ): bool,
            vol.Required(
                CONF_REVERSE_ENABLED,
                default=user_input.get(
                    CONF_REVERSE_ENABLED,
                    DEFAULT_REVERSE_ENABLED,
                ),
            ): bool,
            vol.Required(
                CONF_RECONNECT_INTERVAL,
                default=user_input.get(
                    CONF_RECONNECT_INTERVAL,
                    DEFAULT_RECONNECT_INTERVAL,
                ),
            ): int,
            vol.Optional(
                CONF_BLOCKLIST_INTEGRATIONS,
                default=user_input.get(
                    CONF_BLOCKLIST_INTEGRATIONS,
                    DEFAULT_BLOCKLIST_INTEGRATIONS,
                ),
            ): str,
            vol.Optional(
                CONF_BLOCKLIST_ENTITY_ID_PREFIXES,
                default=user_input.get(
                    CONF_BLOCKLIST_ENTITY_ID_PREFIXES,
                    DEFAULT_BLOCKLIST_ENTITY_ID_PREFIXES,
                ),
            ): str,
        }
    )


class Plan44IntegrationConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict | None = None) -> FlowResult:
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
                await self.async_set_unique_id(
                    f"{user_input[CONF_HOST]}:{user_input[CONF_PORT]}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"plan44 ({user_input[CONF_HOST]})",
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
        user_input: dict | None = None,
    ) -> FlowResult:
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
                    data={**entry.data, **user_input},
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reconfigure_successful")

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_HOST,
                    default=entry.data.get(CONF_HOST, DEFAULT_PORT),
                ): str,
                vol.Required(
                    CONF_PORT,
                    default=entry.data.get(CONF_PORT, DEFAULT_PORT),
                ): int,
                vol.Required(
                    CONF_VDC_MODEL_NAME,
                    default=entry.data.get(
                        CONF_VDC_MODEL_NAME,
                        DEFAULT_VDC_MODEL_NAME,
                    ),
                ): str,
            }
        )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    def async_get_options_flow(config_entry):
        return Plan44OptionsFlow(config_entry)


class Plan44OptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry) -> None:
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict | None = None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = {**self._config_entry.data, **self._config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(current),
        )
