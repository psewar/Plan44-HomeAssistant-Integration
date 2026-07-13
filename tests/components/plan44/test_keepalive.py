"""The TCP client keepalive keeps the connection (and the push path) alive."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.plan44 import plan44_client as pc


async def test_keepalive_sends_log_over_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After connecting, the client periodically sends a no-op `log` keepalive,
    and stops once disconnected."""
    written: list[bytes] = []

    reader = MagicMock()

    async def _park() -> bytes:
        # The reader loop parks here waiting for inbound data; it must not spin.
        await asyncio.Event().wait()
        return b""

    reader.readline = _park

    writer = MagicMock()
    writer.is_closing.return_value = False
    writer.write = written.append
    writer.drain = AsyncMock()
    writer.wait_closed = AsyncMock()

    monkeypatch.setattr(
        asyncio, "open_connection", AsyncMock(return_value=(reader, writer))
    )
    monkeypatch.setattr(pc, "KEEPALIVE_INTERVAL_SECONDS", 0)

    client = pc.Plan44Client(
        host="127.0.0.1",
        port=8999,
        vdc_model_name="Test",
        incoming_callback=AsyncMock(),
        disconnect_callback=AsyncMock(),
    )

    await client.async_connect()

    async def _seen_log() -> None:
        while not any(b'"message":"log"' in chunk for chunk in written):
            await asyncio.sleep(0)

    await asyncio.wait_for(_seen_log(), timeout=1)

    await client.async_disconnect()
    written.clear()
    await asyncio.sleep(0.05)
    assert not any(b'"message":"log"' in chunk for chunk in written)
