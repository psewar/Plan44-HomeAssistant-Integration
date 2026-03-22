from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import DeviceCommand, DeviceState, VirtualDeviceSpec
from .session import P44Session

type JsonDict = dict[str, Any]


class TraceRecorder:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    async def __call__(self, direction: str, message: JsonDict) -> None:
        record: JsonDict = {
            "timestamp": datetime.now(UTC).isoformat(),
            "direction": direction,
            "message": message,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


class P44TestHarness:
    def __init__(self, session: P44Session) -> None:
        self.session = session

    async def connect(self) -> None:
        await self.session.connect()

    async def provision(self, specs: Iterable[VirtualDeviceSpec]) -> None:
        for spec in specs:
            await self.session.register_device(spec)

    async def set_state(self, spec: VirtualDeviceSpec, state: DeviceState) -> None:
        await self.session.push_state(spec.device_id, state)

    async def wait_for_command(self, timeout: float = 5.0) -> DeviceCommand | None:
        return await self.session.wait_for_command(timeout=timeout)

    async def collect_messages_for(self, duration: float = 0.25) -> list[JsonDict]:
        return await self.session.collect_messages_for(duration=duration)

    async def assert_no_error_status(self, duration: float = 0.25) -> None:
        messages = await self.collect_messages_for(duration=duration)
        errors = [
            message
            for message in messages
            if message.get("message") == "status"
            and str(message.get("status", "")).lower() == "error"
        ]
        if errors:
            raise AssertionError(f"P44 returned error status messages: {errors!r}")
