from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from .plan44_core.models import DeviceCommand, DeviceKind, DeviceState, VirtualDeviceSpec
from .plan44_core.protocol import (
    build_channel_message,
    build_init_message,
    build_initvdc_message,
    build_sensor_message,
    parse_incoming_message,
    state_to_messages,
)

_LOGGER = logging.getLogger(__name__)

JsonDict = dict[str, Any]
IncomingCallback = Callable[[JsonDict], Awaitable[None]]
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
        self._reader_task: asyncio.Task[None] | None = None

    @property
    def is_connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def async_connect(self) -> None:
        if self.is_connected:
            return

        self._reader, self._writer = await asyncio.open_connection(
            self.host,
            self.port,
        )
        _LOGGER.info("Connected to plan44 at %s:%s", self.host, self.port)

        await self.async_send(build_initvdc_message(self.vdc_model_name))
        self._reader_task = asyncio.create_task(self._async_reader_loop())

    async def async_ensure_connected(self) -> None:
        if not self.is_connected:
            await self.async_connect()

    async def async_disconnect(self) -> None:
        reader_task = self._reader_task
        if reader_task is not None:
            reader_task.cancel()
            self._reader_task = None

        writer = self._writer
        if writer is not None:
            writer.close()
            await writer.wait_closed()

        self._reader = None
        self._writer = None

    async def async_send(self, payload: JsonDict) -> None:
        async with self._write_lock:
            if not self.is_connected:
                raise RuntimeError("plan44 client is not connected")

            writer = self._writer
            if writer is None:
                raise RuntimeError("plan44 client writer is unavailable")
            line = json.dumps(payload, separators=(",", ":")) + "\n"
            writer.write(line.encode("utf-8"))
            await writer.drain()
            _LOGGER.debug("plan44 tx: %s", line.strip())

    async def async_register_device(
        self,
        uid: str,
        name: str,
        kind: str,
        unit: str | None = None,
    ) -> None:
        spec = VirtualDeviceSpec(
            device_id=uid,
            name=name,
            kind=cast(DeviceKind, kind),
            unit=unit,
        )
        await self.async_send(build_init_message(spec))

    async def async_push_channel_value(self, uid: str, value: int) -> None:
        await self.async_send(build_channel_message(uid, value))

    async def async_push_sensor_value(self, uid: str, value: float) -> None:
        await self.async_send(build_sensor_message(uid, value))

    async def async_push_state_messages(
        self,
        uid: str,
        state: DeviceState,
    ) -> None:
        for message in state_to_messages(uid, state):
            await self.async_send(message)

    def parse_message_as_command(
        self,
        msg: JsonDict,
        kind: str,
    ) -> DeviceCommand | None:
        return parse_incoming_message(msg, cast(DeviceKind, kind))

    async def _async_reader_loop(self) -> None:
        reader = self._reader
        if reader is None:
            raise RuntimeError("plan44 client reader is unavailable")

        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    _LOGGER.warning("plan44 connection closed by remote side")
                    break

                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue

                try:
                    loaded = json.loads(line)
                except json.JSONDecodeError:
                    _LOGGER.warning("Invalid JSON from plan44: %s", line)
                    continue

                if not isinstance(loaded, dict):
                    _LOGGER.warning("Ignoring non-object JSON from plan44: %s", line)
                    continue

                msg: JsonDict = dict(loaded)
                await self._incoming_callback(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            _LOGGER.exception("Unexpected error in plan44 reader loop")
        finally:
            self._reader = None
            writer = self._writer
            if writer is not None:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass
            self._writer = None
            await self._disconnect_callback()
