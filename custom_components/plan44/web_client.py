"""Read-only client for the plan44 web vdc JSON API (device discovery + states).

The plan44 web UI exposes the vdc API at ``POST <base>/api/json/vdc`` behind
HTTP Digest auth.  This client mirrors that: it enumerates devices (with their
sensor/binary-input descriptions, from which HA channel specs are derived) and
reads their current values.

Digest auth is not supported by aiohttp, so the blocking request runs in an
executor via urllib (which has HTTPDigestAuthHandler).  The bridge uses a
self-signed certificate, so it is pinned on first use (trust-on-first-use):
the certificate is fetched + stored once, and later calls verify the peer
against exactly that certificate instead of trusting any/no certificate.
"""

from __future__ import annotations

import json
import logging
import math
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, TypeGuard

from homeassistant.core import HomeAssistant

from .const import DEVICE_ACTIVE

_LOGGER = logging.getLogger(__name__)

PLATFORM_SENSOR = "sensor"
PLATFORM_BINARY_SENSOR = "binary_sensor"

# Guard rails against a malformed/hostile bridge response.
_MAX_RESPONSE_BYTES = 8 * 1024 * 1024  # 8 MiB is far above any real vdc reply
_MAX_PARSE_DEPTH = 64  # the real reply nests ~6 levels; 64 is generous

DEFAULT_HTTPS_PORT = 443
_CERT_FETCH_TIMEOUT = 15.0

# The vdcd bridge periodically closes the connection from its side ("connection
# closed by remote side", often in short bursts).  A request that lands in that
# window comes back as a reset socket or an empty body -- a single blip would
# otherwise abort whatever automation triggered it (e.g. the sunrise wake-up
# light).  Retry a few times with a short, growing pause so an isolated drop
# turns into a successful call instead of a hard failure.
_REQUEST_ATTEMPTS = 3
_REQUEST_RETRY_DELAY = 0.8  # seconds; multiplied by the attempt number

# dS sensorType -> (HA device_class, state_class). Unmapped types → plain sensor.
_SENSOR_TYPE: dict[int, tuple[str | None, str | None]] = {
    1: ("temperature", "measurement"),
    2: ("humidity", "measurement"),
    4: ("voltage", "measurement"),
    9: ("illuminance", "measurement"),
    11: (None, "measurement"),  # set point (relative 0..1)
    13: ("wind_speed", "measurement"),
    14: ("power", "measurement"),
    15: ("current", "measurement"),
    16: ("energy", "total_increasing"),
    18: ("atmospheric_pressure", "measurement"),
    19: (None, "measurement"),  # angle / direction
    21: ("precipitation", "measurement"),
    23: ("wind_speed", "measurement"),
    29: ("distance", "measurement"),
}

# plan44 siunit string -> HA unit_of_measurement.
_SIUNIT: dict[str, str] = {
    "celsius": "°C",
    "percent": "%",
    "volt": "V",
    "ampere": "A",
    "watt": "W",
    "kilowatthour": "kWh",
    "hectopascal": "hPa",
    "meter": "m",
    "meterpersecond": "m/s",
    "degree": "°",
    "millimperm2": "mm",
    "lux": "lx",
}

# dS binary input sensorFunction -> HA binary_sensor device_class.
_INPUT_FUNCTION: dict[int, str] = {
    5: "motion",
    7: "smoke",
    12: "battery",
}


@dataclass(frozen=True, slots=True)
class DiscoveredChannel:
    key: str  # description key, also used to read the matching state
    name: str
    platform: str
    unit: str | None = None
    device_class: str | None = None
    state_class: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveredDevice:
    dsuid: str
    name: str
    model: str
    channels: tuple[DiscoveredChannel, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class DiscoveredLightDevice:
    """A plan44 device that has light output channels (brightness at minimum)."""

    dsuid: str
    name: str
    model: str
    # Real hardware vendor as the bridge reports it (e.g. "Signify Netherlands
    # B.V." for a Hue lamp). Empty when the bridge does not say, in which case
    # the device falls back to being attributed to plan44.
    vendor: str
    has_color_temp: bool
    color_temp_min_mired: float
    color_temp_max_mired: float
    has_hs_color: bool
    has_xy_color: bool


@dataclass(frozen=True, slots=True)
class LightChannelState:
    """Current channel values for a light output device."""

    brightness: float  # 0.0–100.0
    color_temp_mired: float | None  # mired; None when unavailable
    hue: float | None  # 0.0–360.0; None for non-colour lights
    saturation: float | None  # 0.0–100.0; None for non-colour lights
    x: float | None  # CIE x chromaticity; None for non-colour lights
    y: float | None  # CIE y chromaticity; None for non-colour lights


def default_web_url(host: str | None) -> str | None:
    """Derive the web API base URL from the connection host (https on 443).

    The web UI lives on the same host as the TCP API, just over HTTPS, so the
    user only needs to supply credentials — the URL defaults to ``https://<host>``.
    """
    if not host:
        return None
    host = str(host).strip()
    if not host:
        return None
    if host.startswith(("http://", "https://")):
        return host.rstrip("/")
    return f"https://{host}"


def build_ssl_context(
    pinned_cert: str | None, verify_ssl: bool = True
) -> ssl.SSLContext:
    """Build the TLS context for talking to the bridge.

    With a pinned certificate we trust *only* that certificate (the bridge's
    self-signed cert is its own anchor), giving MITM protection.  Hostname
    checking is off because self-signed certs rarely match the host/IP and the
    exact-cert pin already binds the connection.  Without a pin (before the
    first fetch, or if the fetch failed) we fall back to no verification.

    When *verify_ssl* is False all certificate checks are skipped entirely;
    this disables TOFU protection and is intended only as a temporary workaround
    for CA-chain issues (e.g. while a new certificate is being rolled out).
    """
    if not verify_ssl:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    if pinned_cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.load_verify_locations(cadata=pinned_cert)
        return ctx
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch_server_cert_pem(
    base_url: str, timeout: float = _CERT_FETCH_TIMEOUT
) -> str | None:
    """Fetch the bridge's TLS certificate (PEM) for trust-on-first-use pinning.

    Returns ``None`` if the host is unreachable or no certificate is presented;
    the caller then keeps working unpinned until a fetch succeeds.
    """
    parsed = urllib.parse.urlparse(base_url)
    host = parsed.hostname
    if not host:
        return None
    port = parsed.port or DEFAULT_HTTPS_PORT
    try:
        return ssl.get_server_certificate((host, port), timeout=timeout)
    except (OSError, ValueError) as err:
        _LOGGER.warning(
            "plan44: could not fetch bridge certificate for pinning (%s); "
            "continuing without certificate verification",
            err,
        )
        return None


class Plan44WebApiError(Exception):
    """Raised when the web API cannot be queried."""


class Plan44WebApi:
    """Minimal async wrapper around the plan44 web vdc JSON API."""

    def __init__(
        self,
        hass: HomeAssistant,
        base_url: str,
        user: str,
        password: str,
        pinned_cert: str | None = None,
        verify_ssl: bool = True,
    ) -> None:
        self._hass = hass
        self._base = base_url.rstrip("/")
        self._user = user
        self._password = password
        self._pinned_cert = pinned_cert
        self._verify_ssl = verify_ssl

    @property
    def base_url(self) -> str:
        return self._base

    async def async_list_devices(self) -> list[DiscoveredDevice]:
        payload = await self._hass.async_add_executor_job(
            self._request_sync, _DESCRIPTIONS_QUERY
        )
        return parse_devices(payload)

    async def async_get_states(self, dsuids: set[str]) -> dict[str, dict[str, Any]]:
        payload = await self._hass.async_add_executor_job(
            self._request_sync, _STATES_QUERY
        )
        return parse_states(payload, dsuids)

    async def async_list_light_devices(self) -> list[DiscoveredLightDevice]:
        payload = await self._hass.async_add_executor_job(
            self._request_sync, _LIGHT_DESCRIPTIONS_QUERY
        )
        return parse_light_devices(payload)

    async def async_get_light_states(
        self, dsuids: set[str]
    ) -> dict[str, dict[str, Any]]:
        payload = await self._hass.async_add_executor_job(
            self._request_sync, _LIGHT_STATES_QUERY
        )
        return parse_light_states(payload, dsuids)

    def _set_channels_sync(
        self, dsuid: str, channels: dict[str, float], transition: float | None
    ) -> None:
        """Set one or more channel values on a light device (run in executor).

        Without a transition every channel goes in one setProperty request.
        A fade needs the ``setOutputChannelValue`` notification instead, which
        is the only call that carries ``transitionTime`` (vdcd device.cpp) and
        which the hue vdc forwards to the lamp as the Hue API's own
        ``transitiontime`` (huedevice.cpp) — setProperty has no such parameter
        and would snap. That costs one request per channel, so it is only used
        when a fade was actually asked for.
        """
        if transition is None:
            self._request_sync(
                {
                    "method": "setProperty",
                    "dSUID": dsuid,
                    "properties": {
                        "channelStates": {
                            ch: {"value": val} for ch, val in channels.items()
                        }
                    },
                }
            )
            return

        items = list(channels.items())
        for index, (channel, value) in enumerate(items):
            self._request_sync(
                {
                    "notification": "setOutputChannelValue",
                    "dSUID": dsuid,
                    "channelId": channel,
                    "value": value,
                    "transitionTime": transition,
                    # Apply once, after the last channel, so a colour +
                    # brightness change fades as one move instead of several.
                    "apply_now": index == len(items) - 1,
                }
            )

    async def async_set_channels(
        self,
        dsuid: str,
        channels: dict[str, float],
        transition: float | None = None,
    ) -> None:
        await self._hass.async_add_executor_job(
            self._set_channels_sync, dsuid, channels, transition
        )

    def _identify_sync(self, dsuid: str, duration: float | None) -> None:
        request: dict[str, Any] = {"notification": "identify", "dSUID": dsuid}
        if duration is not None:
            request["duration"] = duration
        self._request_sync(request)

    async def async_identify(self, dsuid: str, duration: float | None = None) -> None:
        """Make the device draw attention to itself (blink), if it can."""
        await self._hass.async_add_executor_job(self._identify_sync, dsuid, duration)

    # -- blocking implementation (runs in executor) ------------------------

    def _request_sync(self, query: dict[str, Any]) -> Any:
        """POST a vdc query, retrying transient bridge drops (runs in executor).

        A reset socket or empty body means the vdcd bridge closed the connection
        mid-request; those are retried a few times.  A certificate problem, an
        auth/HTTP error, or an over-sized response is not transient and fails
        immediately.  ``time.sleep`` here only blocks the executor worker, not
        the event loop.
        """
        last_err: Exception | None = None
        for attempt in range(_REQUEST_ATTEMPTS):
            try:
                return self._request_once(query)
            except ssl.SSLError as err:
                # Certificate mismatch won't fix itself on retry.
                raise Plan44WebApiError(self._cert_error_message(err)) from err
            except (OSError, json.JSONDecodeError) as err:
                last_err = err
                if attempt + 1 < _REQUEST_ATTEMPTS:
                    _LOGGER.debug(
                        "vdc request transient failure (attempt %d/%d), retrying: %s",
                        attempt + 1,
                        _REQUEST_ATTEMPTS,
                        err,
                    )
                    time.sleep(_REQUEST_RETRY_DELAY * (attempt + 1))
        raise Plan44WebApiError(
            f"vdc API request failed after {_REQUEST_ATTEMPTS} attempts: {last_err}"
        ) from last_err

    def _request_once(self, query: dict[str, Any]) -> Any:
        """Perform one vdc request.

        Transient failures (``OSError``, empty/undecodable body →
        ``json.JSONDecodeError``) and ``ssl.SSLError`` propagate to
        :meth:`_request_sync`, which decides whether to retry.  Non-transient
        problems raise :class:`Plan44WebApiError` here so they are not retried.
        """
        ctx = build_ssl_context(self._pinned_cert, verify_ssl=self._verify_ssl)
        pwmgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        pwmgr.add_password(None, self._base, self._user, self._password)
        opener = urllib.request.build_opener(
            urllib.request.HTTPDigestAuthHandler(pwmgr),
            urllib.request.HTTPSHandler(context=ctx),
        )

        token: Any = None
        try:
            with opener.open(self._base + "/tok/json", timeout=15) as tr:
                token = json.loads(self._read_capped(tr))
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise Plan44WebApiError(f"token request failed: {err}") from err

        endpoint = self._base + "/api/json/vdc"
        if token not in (None, True, False):
            endpoint += "?rqvaltok=" + urllib.parse.quote(str(token))

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(query).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with opener.open(req, timeout=20) as resp:
            return json.loads(self._read_capped(resp))

    @staticmethod
    def _read_capped(resp: Any) -> str:
        """Read a response body, refusing anything implausibly large."""
        raw = resp.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise Plan44WebApiError(
                f"vdc API response exceeds {_MAX_RESPONSE_BYTES} bytes; refusing"
            )
        return raw.decode("utf-8")

    @staticmethod
    def _cert_error_message(err: ssl.SSLError) -> str:
        return (
            "TLS certificate verification failed — the bridge certificate may "
            "have changed. Remove and re-add the plan44 web credentials in the "
            f"options to re-pin the new certificate. ({err})"
        )


_DESCRIPTIONS_QUERY: dict[str, Any] = {
    "method": "getProperty",
    "dSUID": "",
    "query": {
        "x-p44-vdcs": {
            "*": {
                "x-p44-devices": {
                    "*": {
                        "dSUID": None,
                        "name": None,
                        "model": None,
                        "sensorDescriptions": None,
                        "binaryInputDescriptions": None,
                    }
                }
            }
        }
    },
}

_STATES_QUERY: dict[str, Any] = {
    "method": "getProperty",
    "dSUID": "",
    "query": {
        "x-p44-vdcs": {
            "*": {
                "x-p44-devices": {
                    "*": {
                        "dSUID": None,
                        "active": None,
                        "sensorStates": None,
                        "binaryInputStates": None,
                    }
                }
            }
        }
    },
}


_LIGHT_DESCRIPTIONS_QUERY: dict[str, Any] = {
    "method": "getProperty",
    "dSUID": "",
    "query": {
        "x-p44-vdcs": {
            "*": {
                "x-p44-devices": {
                    "*": {
                        "dSUID": None,
                        "name": None,
                        "model": None,
                        "vendorName": None,
                        "outputSettings": None,
                        "channelDescriptions": None,
                    }
                }
            }
        }
    },
}

_LIGHT_STATES_QUERY: dict[str, Any] = {
    "method": "getProperty",
    "dSUID": "",
    "query": {
        "x-p44-vdcs": {
            "*": {
                "x-p44-devices": {
                    "*": {
                        "dSUID": None,
                        "active": None,
                        "channelStates": None,
                    }
                }
            }
        }
    },
}


def _iter_devices(payload: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(node: Any, depth: int) -> None:
        if depth > _MAX_PARSE_DEPTH:
            _LOGGER.warning(
                "plan44 web API response nested deeper than %s levels; stopping",
                _MAX_PARSE_DEPTH,
            )
            return
        if isinstance(node, dict):
            if "dSUID" in node and (
                "sensorDescriptions" in node
                or "binaryInputDescriptions" in node
                or "sensorStates" in node
                or "binaryInputStates" in node
            ):
                found.append(node)
            for value in node.values():
                visit(value, depth + 1)
        elif isinstance(node, list):
            for value in node:
                visit(value, depth + 1)

    visit(payload, 0)
    return found


def _items(container: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(container, dict):
        return [(str(k), v) for k, v in container.items() if isinstance(v, dict)]
    if isinstance(container, list):
        return [(str(i), v) for i, v in enumerate(container) if isinstance(v, dict)]
    return []


def _sensor_channel(key: str, descr: dict[str, Any]) -> DiscoveredChannel:
    stype = descr.get("sensorType")
    if isinstance(stype, (int, float)):
        device_class, state_class = _SENSOR_TYPE.get(int(stype), (None, "measurement"))
    else:
        device_class, state_class = None, "measurement"
    unit = _SIUNIT.get(str(descr.get("siunit", "")).lower())
    return DiscoveredChannel(
        key=key,
        name=str(descr.get("name") or key),
        platform=PLATFORM_SENSOR,
        unit=unit,
        device_class=device_class,
        state_class=state_class,
    )


def _input_channel(key: str, descr: dict[str, Any]) -> DiscoveredChannel:
    fn = descr.get("sensorFunction")
    device_class = (
        _INPUT_FUNCTION.get(int(fn)) if isinstance(fn, (int, float)) else None
    )
    return DiscoveredChannel(
        key=key,
        name=str(descr.get("name") or key),
        platform=PLATFORM_BINARY_SENSOR,
        device_class=device_class,
    )


def parse_devices(payload: Any) -> list[DiscoveredDevice]:
    devices: list[DiscoveredDevice] = []
    for dev in _iter_devices(payload):
        channels: list[DiscoveredChannel] = []
        for key, descr in _items(dev.get("sensorDescriptions")):
            channels.append(_sensor_channel(key, descr))
        for key, descr in _items(dev.get("binaryInputDescriptions")):
            channels.append(_input_channel(key, descr))
        if not channels:
            continue  # nothing HA can show as a sensor/binary_sensor
        devices.append(
            DiscoveredDevice(
                dsuid=str(dev["dSUID"]),
                name=str(dev.get("name") or dev["dSUID"]),
                model=str(dev.get("model") or ""),
                channels=tuple(channels),
            )
        )
    return devices


def parse_states(payload: Any, dsuids: set[str]) -> dict[str, dict[str, Any]]:
    """Map dSUID -> {"sensor": {...}, "binary_sensor": {...}, "active": bool|None}.

    Mirrors DeviceStates in device_coordinator: the per-platform channel maps
    sit next to the bridge's own active flag, so an entity can tell "no value
    yet" apart from "this device stopped reporting".
    """
    result: dict[str, dict[str, Any]] = {}
    for dev in _iter_devices(payload):
        dsuid = str(dev.get("dSUID"))
        if dsuid not in dsuids:
            continue
        sensors: dict[str, Any] = {}
        for key, state in _items(dev.get("sensorStates")):
            sensors[key] = state.get("value")
        inputs: dict[str, Any] = {}
        for key, state in _items(dev.get("binaryInputStates")):
            inputs[key] = state.get("value")
        result[dsuid] = {
            PLATFORM_SENSOR: sensors,
            PLATFORM_BINARY_SENSOR: inputs,
            # The bridge knows when a device has stopped reporting; without this
            # the entities keep claiming to be available and just sit on
            # "unknown" forever. A bridge that omits the field leaves it None,
            # which is treated as "no opinion" (= available).
            DEVICE_ACTIVE: dev.get("active"),
        }
    return result


def _iter_light_nodes(payload: Any) -> list[dict[str, Any]]:
    """Yield device nodes that carry channel data (descriptions or states)."""
    found: list[dict[str, Any]] = []

    def visit(node: Any, depth: int) -> None:
        if depth > _MAX_PARSE_DEPTH:
            return
        if isinstance(node, dict):
            if "dSUID" in node and (
                "channelDescriptions" in node or "channelStates" in node
            ):
                found.append(node)
            for value in node.values():
                visit(value, depth + 1)
        elif isinstance(node, list):
            for value in node:
                visit(value, depth + 1)

    visit(payload, 0)
    return found


def _is_finite_number(value: Any) -> TypeGuard[int | float]:
    """True for a real, finite number.

    ``json.loads`` accepts bare ``NaN``/``Infinity``, and those pass a plain
    isinstance check — then blow up later in ``round()``/Decimal conversions,
    inside a coordinator listener where the traceback costs every entity that
    would have been updated after it.
    """
    return isinstance(value, (int, float)) and math.isfinite(value)


def _ch_float(
    channel_descs: dict[str, Any], key: str, attr: str, default: float
) -> float:
    ch = channel_descs.get(key)
    if isinstance(ch, dict):
        v = ch.get(attr)
        if _is_finite_number(v):
            return float(v)
    return default


def _channel_state_value(channel_states: dict[str, Any], key: str) -> float | None:
    ch = channel_states.get(key)
    if not isinstance(ch, dict):
        return None
    v = ch.get("value")
    # None is already the "channel unavailable" signal everywhere downstream.
    return float(v) if _is_finite_number(v) else None


def parse_light_devices(payload: Any) -> list[DiscoveredLightDevice]:
    devices: list[DiscoveredLightDevice] = []
    for dev in _iter_light_nodes(payload):
        channel_descs = dev.get("channelDescriptions")
        if not isinstance(channel_descs, dict) or "brightness" not in channel_descs:
            continue
        if not isinstance(dev.get("outputSettings"), dict):
            continue
        has_color_temp = "colortemp" in channel_descs
        ct_min = _ch_float(channel_descs, "colortemp", "min", 100.0)
        ct_max = _ch_float(channel_descs, "colortemp", "max", 1000.0)
        devices.append(
            DiscoveredLightDevice(
                dsuid=str(dev["dSUID"]),
                name=str(dev.get("name") or dev["dSUID"]),
                model=str(dev.get("model") or ""),
                vendor=str(dev.get("vendorName") or ""),
                has_color_temp=has_color_temp,
                color_temp_min_mired=ct_min,
                color_temp_max_mired=ct_max,
                has_hs_color="hue" in channel_descs and "saturation" in channel_descs,
                has_xy_color="x" in channel_descs and "y" in channel_descs,
            )
        )
    return devices


def parse_light_states(payload: Any, dsuids: set[str]) -> dict[str, dict[str, Any]]:
    """Map dSUID -> {"light": LightChannelState, "active": bool | None}.

    Mirrors parse_states so a light can tell "no value yet" apart from "the
    bridge says this device stopped reporting" — a Hue lamp cut from power at
    the wall switch keeps its node and its last channel values, and only the
    active flag gives it away.
    """
    result: dict[str, dict[str, Any]] = {}
    for dev in _iter_light_nodes(payload):
        dsuid = str(dev.get("dSUID"))
        if dsuid not in dsuids:
            continue
        channel_states = dev.get("channelStates")
        if not isinstance(channel_states, dict):
            continue
        ls = parse_push_light_channel_states(channel_states)
        if ls is None:
            continue
        result[dsuid] = {"light": ls, DEVICE_ACTIVE: dev.get("active")}
    return result


def parse_push_light_channel_states(
    channel_states: dict[str, Any],
) -> LightChannelState | None:
    """Parse a channelStates dict from a TCP push notification.

    Takes the inner ``channelStates`` mapping directly — same structure the HTTP
    poll returns, but without the outer API envelope.
    """
    brightness = _channel_state_value(channel_states, "brightness")
    if brightness is None:
        return None
    return LightChannelState(
        brightness=brightness,
        color_temp_mired=_channel_state_value(channel_states, "colortemp"),
        hue=_channel_state_value(channel_states, "hue"),
        saturation=_channel_state_value(channel_states, "saturation"),
        x=_channel_state_value(channel_states, "x"),
        y=_channel_state_value(channel_states, "y"),
    )
