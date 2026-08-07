"""Setup/teardown lifecycle: nothing may outlive a failed setup or an unload."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant


async def test_setup_failure_tears_down_the_client(
    hass: HomeAssistant, config_entry: Any, mock_plan44_client: Any
) -> None:
    """A failure after async_initialize() must not leak the connection.

    async_initialize() opens the socket and starts the reader/keepalive tasks
    and the state listener. Home Assistant only runs async_unload_entry for a
    *successful* setup, so a raise in between used to leave all of it running —
    and every retry added another coordinator whose (unbounded) reconnect loop
    nothing would ever cancel.
    """
    with (
        patch(
            "custom_components.plan44.Plan44Coordinator.async_initialize",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch(
            "custom_components.plan44.Plan44Coordinator.async_shutdown",
            new=AsyncMock(),
        ) as shutdown,
    ):
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_RETRY
    shutdown.assert_awaited()


async def test_setup_failure_after_platforms_tears_down(
    hass: HomeAssistant, config_entry: Any, mock_plan44_client: Any
) -> None:
    """The same holds for a failure while forwarding the platforms."""
    with (
        patch(
            "homeassistant.config_entries.ConfigEntries.async_forward_entry_setups",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch(
            "custom_components.plan44.Plan44Coordinator.async_shutdown",
            new=AsyncMock(),
        ) as shutdown,
    ):
        # Home Assistant catches the error itself and marks the entry failed;
        # what matters is that we cleaned up on the way out.
        await hass.config_entries.async_setup(config_entry.entry_id)
        await hass.async_block_till_done()

    assert config_entry.state is ConfigEntryState.SETUP_ERROR
    shutdown.assert_awaited()


async def test_forward_after_shutdown_does_not_reconnect(
    hass: HomeAssistant, config_entry: Any, mock_plan44_client: Any
) -> None:
    """A forward task queued before teardown must not re-open the connection.

    async_forward_entity_state() calls async_ensure_connected(); without the
    guard, a task suspended inside open_connection() during a reload would
    create a socket + reader + keepalive that nothing owns.
    """
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    coordinator = config_entry.runtime_data.coordinator

    await coordinator.async_shutdown()
    mock_plan44_client.async_ensure_connected.reset_mock()

    await coordinator.async_forward_entity_state("sensor.demo")

    mock_plan44_client.async_ensure_connected.assert_not_called()
