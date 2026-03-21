from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .models import DeviceCommand, DeviceState, VirtualDeviceSpec
from .protocol import (
    build_init_message,
    build_initvdc_message,
    parse_incoming_message,
    state_to_messages,
)

_LOGGER = logging.getLogger(__name__)

JsonDict = dict[str, Any]
TraceHook = Callable[[str, JsonDict], Awaitable[None]]
IncomingHook = Callable[[JsonDict], Awaitable[None]]


class P44Session:
    def __init__(
        self,
        host: str,
        port: int,
        model_name: str,
        trace_hook: TraceHook | None = None,
        incoming_hook: IncomingHook | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.model_name = model_name
        self._trace_hook = trace_hook
        self._incoming_hook = incoming_hook
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task[None] | None = None
        self._queue: asyncio.Queue[JsonDict] = asyncio.Queue()
        self._specs_by_id: dict[str, VirtualDeviceSpec] = {}
        self._write_lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def connect(self) -> None:
        if self.is_connected:
            return
        self._reader, self._writer = await asyncio.open_connection(
            self.host,
            self.port,
        )
        await self.send_message(build_initvdc_message(self.model_name))
        self._read_task = asyncio.create_task(self._read_loop())

    async def disconnect(self) -> None:
        if self._read_task is not None:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
            self._read_task = None
        if self._writer is not None:
            self._writer.close()
            await self._writer.wait_closed()
        self._reader = None
        self._writer = None

    async def register_device(self, spec: VirtualDeviceSpec) -> None:
        await self.connect()
        self._specs_by_id[spec.device_id] = spec
        await self.send_message(build_init_message(spec))

    async def push_state(self, device_id: str, state: DeviceState) -> None:
        await self.connect()
        for message in state_to_messages(device_id, state):
            await self.send_message(message)

    async def send_message(self, message: JsonDict) -> None:
        async with self._write_lock:
            if not self.is_connected:
                raise RuntimeError("P44 session is not connected")
            writer = self._writer
            if writer is None:
                raise RuntimeError("P44 session writer is unavailable")
            line = json.dumps(message, separators=(",", ":")) + "\n"
            writer.write(line.encode("utf-8"))
            await writer.drain()
            await self._emit_trace("tx", message)

    async def wait_for_message(self, timeout: float = 5.0) -> JsonDict:
        return await asyncio.wait_for(self._queue.get(), timeout=timeout)

    async def wait_for_command(self, timeout: float = 5.0) -> DeviceCommand | None:
        while True:
            message = await self.wait_for_message(timeout=timeout)
            tag = message.get("tag")
            if tag is None:
                continue
            spec = self._specs_by_id.get(str(tag))
            if spec is None:
                continue
            command = parse_incoming_message(message, spec.kind)
            if command is not None:
                return command

    async def _read_loop(self) -> None:
        reader = self._reader
        if reader is None:
            raise RuntimeError("P44 session reader is unavailable")
        try:
            while True:
                raw = await reader.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="ignore").strip()
                if not line:
                    continue
                try:
                    loaded = json.loads(line)
                except json.JSONDecodeError:
                    _LOGGER.warning("Ignoring invalid JSON from P44: %s", line)
                    continue
                if not isinstance(loaded, dict):
                    _LOGGER.warning("Ignoring non-object JSON from P44: %s", line)
                    continue
                message: JsonDict = dict(loaded)
                await self._emit_trace("rx", message)
                await self._queue.put(message)
                if self._incoming_hook is not None:
                    await self._incoming_hook(message)
        except asyncio.CancelledError:
            raise
        finally:
            self._reader = None
            self._writer = None

    async def _emit_trace(self, direction: str, message: JsonDict) -> None:
        if self._trace_hook is not None:
            await self._trace_hook(direction, message)
