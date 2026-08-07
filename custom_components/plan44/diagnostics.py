from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data

from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_RESET_SSH_HOST_KEY,
    CONF_SSH_HOST,
    CONF_SSH_HOST_KEY,
    CONF_SSH_PORT,
    CONF_SSH_PRIVATE_KEY,
    CONF_SSH_USER,
    CONF_VDC_MODEL_NAME,
    CONF_WEB_CERT,
    CONF_WEB_PASSWORD,
    CONF_WEB_USER,
    Plan44ConfigEntry,
)

# Diagnostics are downloaded and routinely shared (issues, forums), so anything
# secret or identifying must be redacted.  The credentials are the critical
# ones — above all the SSH private key, which grants access to the bridge —
# hosts/ports/model/certificate are redacted as a courtesy.
#
# NOTE: when a new credential-ish option is added, it MUST be added here too.
TO_REDACT = {
    CONF_HOST,
    CONF_PORT,
    CONF_VDC_MODEL_NAME,
    CONF_WEB_USER,
    CONF_WEB_PASSWORD,
    CONF_WEB_CERT,
    CONF_SSH_HOST,
    CONF_SSH_PORT,
    CONF_SSH_USER,
    CONF_SSH_PRIVATE_KEY,
    CONF_SSH_HOST_KEY,
    # Not a secret (a transient flag that is never persisted), but the guard
    # test is deliberately strict: redacting a non-secret costs nothing,
    # while an allowlist could be used to wave through a real one.
    CONF_RESET_SSH_HOST_KEY,
}


async def async_get_config_entry_diagnostics(
    hass: Any,
    entry: Plan44ConfigEntry,
) -> dict[str, Any]:
    runtime = entry.runtime_data

    data: dict[str, Any] = {
        "entry_data": dict(entry.data),
        "entry_options": dict(entry.options),
        "exports": runtime.store.data,
        "client_connected": runtime.client.is_connected,
        # Real-time (bridge API over SSH) link — None when the mode is off.
        "realtime_connected": (
            runtime.bridge_client.connected
            if runtime.bridge_client is not None
            else None
        ),
        # Whether the bridge TLS certificate is actually pinned (a failed
        # trust-on-first-use fetch silently falls back to no verification).
        "web_cert_pinned": bool(entry.data.get(CONF_WEB_CERT)),
    }

    return async_redact_data(data, TO_REDACT)
