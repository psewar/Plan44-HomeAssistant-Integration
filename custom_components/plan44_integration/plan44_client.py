from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

_LOGGER = logging.getLogger(__name__)

IncomingCallback = Callable[[dict[str, Any]], Awaitable[None]]
DisconnectCallback = Callable[[], Awaitable[None]]


class Plan44Client:
    def __init__(
        self,
        host: str,
        port: int,
        vdc_model_name: str,
        incoming_callback: IncomingCallback,
        disconnect_callback: DisconnectCallback,
    ) -> None:
        self.host = host
        self.port = port
        self.vdc_model_name = vdc_model_name
        self._incoming_callback = incoming_callback
        self._disconnect_callback = disconnect_callback

        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._write_lock = asyncio.Lock()
        self._reader_task: asyncio.Task | None = None

    @property
    def is_connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def async_connect(self) -> None:
        if self.is_connected:
            return

        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        _LOGGER.info("Connected to plan44 at %s:%s", self.host, self.port)

        await self.async_send({"message": "initvdc", "model": self.vdc_model_name})
        self._reader_task = asyncio.create_task(self._async_reader_loop())

    async def async_ensure_connected(self) -> None:
        if not self.is_connected:
            await self.async_connect()

    async def async_disconnect(self) -> None:
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None

        if self._writer:
            self._writer.close()
            await self._writer.wait_closed()

        self._reader = None
        self._writer = None

    async def async_send(self, payload: dict[str, Any]) -> None:
        async with self._write_lock:
            if not self.is_connected:
                raise RuntimeError("plan44 client is not connected")

            assert self._writer is not None
            line = json.dumps(payload, separators=(",", ":")) + "\n"
            self._writer.write(line.encode("utf-8"))
            await self._writer.drain()
            _LOGGER.debug("plan44 tx: %s", line.strip())

    async def async_register_switch_like(self, uid: str, name: str) -> None:
        await self.async_send(
            {
                "message": "init",
                "tag": uid,
                "name": name,
                "model": "Home Assistant Virtual Device",
                "iconname": "vdc_ext",
                "output": "switch",
                "sync": True,
            }
        )

    async def async_register_sensor(self, uid: str, name: str, unit: str | None = None) -> None:
        await self.async_send(
            {
                "message": "init",
                "tag": uid,
                "name": name,
                "model": "Home Assistant Virtual Sensor",
                "iconname": "vdc_ext",
                "sensor": unit or "generic",
                "sync": True,
            }
        )

    async def async_push_channel_value(self, uid: str, value: int) -> None:
        await self.async_send(
            {
                "message": "channel",
                "tag": uid,
                "index": 0,
                "value": max(0, min(100, int(value))),
            }
        )

    async def async_push_sensor_value(self, uid: str, value: float) -> None:
        await self.async_send(
            {
                "message": "sensor",
                "tag": uid,
                "index": 0,
                "value": value,
            }
        )

    async def _async_reader_loop(self) -> None:
        assert self._reader is not None

        try:
            while True:
                raw = await self._reader.readline()
                if not raw:
                    _LOGGER.warning("plan44 connection closed by remote side")
                    break

                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    _LOGGER.warning("Invalid JSON from plan44: %s", line)
                    continue

                await self._incoming_callback(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Unexpected error in plan44 reader loop")
        finally:
            self._reader = None
            if self._writer:
                try:
                    self._writer.close()
                    await self._writer.wait_closed()
                except Exception:
                    pass
            self._writer = None
            await self._disconnect_callback()
