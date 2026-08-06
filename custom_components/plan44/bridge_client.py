"""Real-time client for the plan44 vdcd *bridge API* over an SSH tunnel.

The bridge API listens on ``127.0.0.1:<bridge_port>`` on the bridge (localhost
only), so we reach it through an SSH ``direct-tcpip`` channel: connect to the
bridge host over SSH (dedicated, forward-only key) and open a forwarded TCP
connection to the local bridge-API port.  Every ``pushNotification`` for a
*bridged* device is then delivered in real time and fed to the polling device
coordinator, so imported entities update instantly instead of on the poll
interval.  The REST poll stays active as a fallback / initial-value backfill.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

import asyncssh
from homeassistant.core import HomeAssistant, callback

from .bridge_protocol import BridgeUpdate, parse_line, parse_push_updates

_LOGGER = logging.getLogger(__name__)

_RECONNECT_MIN_SECONDS = 5
_RECONNECT_MAX_SECONDS = 120

UpdateCallback = Callable[[BridgeUpdate], None]
StatusCallback = Callable[[bool], None]


class Plan44BridgeClient:
    """Maintains an SSH-tunneled connection to the bridge API and streams pushes."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        ssh_host: str,
        ssh_port: int,
        ssh_user: str,
        ssh_private_key: str,
        bridge_port: int,
        on_update: UpdateCallback,
        on_status: StatusCallback | None = None,
    ) -> None:
        self._hass = hass
        self._ssh_host = ssh_host
        self._ssh_port = ssh_port
        self._ssh_user = ssh_user
        self._ssh_private_key = ssh_private_key
        self._bridge_port = bridge_port
        self._on_update = on_update
        self._on_status = on_status
        self._task: asyncio.Task[None] | None = None
        self._closing = False
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def async_start(self) -> None:
        self._closing = False
        if self._task is None or self._task.done():
            self._task = self._hass.async_create_background_task(
                self._run(), "plan44 bridge API client"
            )

    async def async_stop(self) -> None:
        self._closing = True
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError, Exception:  # noqa: BLE001
                pass
        self._set_status(connected=False)

    async def _run(self) -> None:
        delay = _RECONNECT_MIN_SECONDS
        while not self._closing:
            try:
                await self._connect_and_stream()
                delay = _RECONNECT_MIN_SECONDS
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001
                _LOGGER.warning(
                    "plan44 bridge API client error (%s); reconnecting in %ss",
                    err,
                    delay,
                )
            finally:
                self._set_status(connected=False)
            if self._closing:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, _RECONNECT_MAX_SECONDS)

    async def _connect_and_stream(self) -> None:
        key = asyncssh.import_private_key(self._ssh_private_key)
        # known_hosts=None: the bridge is a fixed LAN device; SSH provides the
        # transport encryption/auth. (Host-key pinning is a possible follow-up.)
        async with asyncssh.connect(
            self._ssh_host,
            port=self._ssh_port,
            username=self._ssh_user,
            client_keys=[key],
            known_hosts=None,
        ) as conn:
            reader, writer = await conn.open_connection("127.0.0.1", self._bridge_port)
            self._set_status(connected=True)
            _LOGGER.info(
                "plan44 bridge API connected (ssh %s@%s -> 127.0.0.1:%s)",
                self._ssh_user,
                self._ssh_host,
                self._bridge_port,
            )
            try:
                while not self._closing:
                    raw = await reader.readline()
                    if not raw:
                        break  # EOF / connection closed
                    line = (
                        raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else raw
                    )
                    msg = parse_line(line)
                    if msg is None:
                        continue
                    for update in parse_push_updates(msg):
                        self._dispatch(update)
            finally:
                writer.close()

    @callback
    def _dispatch(self, update: BridgeUpdate) -> None:
        try:
            self._on_update(update)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("plan44 bridge update callback failed")

    def _set_status(self, *, connected: bool) -> None:
        if self._connected == connected:
            return
        self._connected = connected
        if self._on_status is not None:
            self._on_status(connected)
