"""The diagnostics dump must not leak the web API credentials."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from custom_components.plan44 import const as plan44_const
from custom_components.plan44.const import (
    CONF_SSH_PRIVATE_KEY,
    CONF_WEB_PASSWORD,
    CONF_WEB_USER,
)
from custom_components.plan44.diagnostics import (
    TO_REDACT,
    async_get_config_entry_diagnostics,
)


async def test_diagnostics_redacts_web_credentials(
    hass: HomeAssistant, config_entry: Any, mock_plan44_client: Any
) -> None:
    """web_user / web_password are replaced with the redaction marker."""
    hass.config_entries.async_update_entry(
        config_entry,
        data={
            **config_entry.data,
            CONF_WEB_USER: "p44user",
            CONF_WEB_PASSWORD: "sup3rsecret",
        },
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, config_entry)

    assert diag["entry_data"][CONF_WEB_PASSWORD] == "**REDACTED**"
    assert diag["entry_data"][CONF_WEB_USER] == "**REDACTED**"
    # Belt-and-braces: the secret must not appear anywhere in the dump.
    assert "sup3rsecret" not in str(diag)


async def test_diagnostics_redacts_ssh_private_key(
    hass: HomeAssistant, config_entry: Any, mock_plan44_client: Any
) -> None:
    """The SSH private key grants bridge access — it must never be dumped."""
    # Deliberately not a real PEM header, so secret scanners don't flag the test.
    secret_key = "PRIVATE-KEY-PLACEHOLDER-of0rtEsTs-should-never-be-dumped"
    hass.config_entries.async_update_entry(
        config_entry,
        data={**config_entry.data, CONF_SSH_PRIVATE_KEY: secret_key},
    )
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    diag = await async_get_config_entry_diagnostics(hass, config_entry)

    assert diag["entry_data"][CONF_SSH_PRIVATE_KEY] == "**REDACTED**"
    assert "PRIVATE-KEY-PLACEHOLDER" not in str(diag)


def test_every_credential_option_is_redacted() -> None:
    """Guard: any credential-ish CONF_* constant must be in TO_REDACT.

    This is the regression that let the SSH private key leak — a new option was
    added without extending TO_REDACT. Fail loudly instead of leaking again.
    """
    sensitive_markers = ("PASSWORD", "SSH", "SECRET", "TOKEN", "KEY", "CERT")
    missing = [
        name
        for name in dir(plan44_const)
        if name.startswith("CONF_")
        and any(marker in name for marker in sensitive_markers)
        and getattr(plan44_const, name) not in TO_REDACT
    ]
    assert not missing, f"credential-ish options missing from TO_REDACT: {missing}"
