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

RECONNECT_MIN_SECONDS = 5
RECONNECT_MAX_SECONDS = 120
# Only treat a session as "healthy enough to retry fast" once it has lived this
# long; otherwise a tunnel that opens and instantly EOFs would spin at the
# minimum delay forever.
HEALTHY_SESSION_SECONDS = 60
# The bridge-API stream is mostly idle between value changes; a firewall port
# forward or proxy can drop an idle TCP session. SSH-level keepalives keep the
# connection (and the NAT state along the way) alive and detect a dead peer.
SSH_KEEPALIVE_SECONDS = 15
SSH_KEEPALIVE_COUNT_MAX = 4

UpdateCallback = Callable[[BridgeUpdate], None]
StatusCallback = Callable[[bool], None]
HostKeyCallback = Callable[[str], None]


class Plan44BridgeHostKeyError(Exception):
    """The bridge presented a host key that does not match the pinned one."""


def pinned_known_hosts(host_key: str) -> bytes:
    """known_hosts file contents pinning exactly this one host key."""
    return f"* {host_key.strip()}\n".encode()


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
        pinned_host_key: str | None = None,
        on_host_key: HostKeyCallback | None = None,
    ) -> None:
        self._hass = hass
        self._ssh_host = ssh_host
        self._ssh_port = ssh_port
        self._ssh_user = ssh_user
        self._ssh_private_key = ssh_private_key
        self._bridge_port = bridge_port
        self._on_update = on_update
        self._on_status = on_status
        self._pinned_host_key = pinned_host_key
        self._on_host_key = on_host_key
        self._task: asyncio.Task[None] | None = None
        self._closing = False
        self._connected = False
        self._session_started = False

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
            except asyncio.CancelledError:
                # Cancelling our own task is the expected path here; do NOT let
                # it propagate (and do not swallow a cancellation aimed at us —
                # async_stop is only ever awaited from unload).
                pass
            except Exception:  # noqa: BLE001
                _LOGGER.debug(
                    "plan44 bridge client stopped with an error", exc_info=True
                )
        self._set_status(connected=False)

    async def _run(self) -> None:
        delay = RECONNECT_MIN_SECONDS
        while not self._closing:
            self._session_started = False
            started_at = self._hass.loop.time()
            try:
                await self._connect_and_stream()
            except asyncio.CancelledError:
                raise
            except Plan44BridgeHostKeyError as err:
                # Security-relevant: do not paper over it with a retry message.
                _LOGGER.error("plan44 bridge API host key rejected: %s", err)
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
            # Only a session that actually stayed up proves the config is good.
            # Resetting on any session would spin at the minimum delay forever
            # when the tunnel opens and immediately EOFs.
            lived = self._hass.loop.time() - started_at
            if self._session_started and lived >= HEALTHY_SESSION_SECONDS:
                delay = RECONNECT_MIN_SECONDS
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_SECONDS)

    async def _connect_and_stream(self) -> None:
        key = asyncssh.import_private_key(self._ssh_private_key)
        # Trust-on-first-use host-key pinning: once a host key is known, only
        # that exact key is accepted, so a man-in-the-middle on the SSH path is
        # rejected instead of silently relaying the tunnel.
        known_hosts = (
            pinned_known_hosts(self._pinned_host_key) if self._pinned_host_key else None
        )
        try:
            conn_ctx = asyncssh.connect(
                self._ssh_host,
                port=self._ssh_port,
                username=self._ssh_user,
                client_keys=[key],
                known_hosts=known_hosts,
                keepalive_interval=SSH_KEEPALIVE_SECONDS,
                keepalive_count_max=SSH_KEEPALIVE_COUNT_MAX,
            )
        except asyncssh.HostKeyNotVerifiable as err:  # pragma: no cover - defensive
            raise Plan44BridgeHostKeyError(str(err)) from err

        try:
            conn = await conn_ctx
        except asyncssh.HostKeyNotVerifiable as err:
            raise Plan44BridgeHostKeyError(
                "the bridge presented an unexpected SSH host key — refusing to "
                "connect. If the bridge was reinstalled, clear the stored host "
                "key by turning real-time mode off and on again in the options"
            ) from err

        async with conn:
            if self._pinned_host_key is None:
                self._remember_host_key(conn)
            reader, writer = await conn.open_connection("127.0.0.1", self._bridge_port)
            self._session_started = True
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

    def _remember_host_key(self, conn: asyncssh.SSHClientConnection) -> None:
        """Capture the host key on first use so later sessions can pin it."""
        host_key = conn.get_server_host_key()
        if host_key is None or self._on_host_key is None:
            return
        line = host_key.export_public_key("openssh").decode().strip()
        self._pinned_host_key = line
        _LOGGER.info(
            "plan44 bridge: pinned SSH host key (%s) of %s on first use",
            host_key.get_algorithm(),
            self._ssh_host,
        )
        self._on_host_key(line)

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
