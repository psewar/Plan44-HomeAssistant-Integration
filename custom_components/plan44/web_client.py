"""Read-only client for the plan44 web vdc JSON API (device discovery + states).

The plan44 web UI exposes the vdc API at ``POST <base>/api/json/vdc`` behind
HTTP Digest auth.  This client mirrors that: it enumerates devices (with their
sensor/binary-input descriptions, from which HA channel specs are derived) and
reads their current values.

Digest auth is not supported by aiohttp, so the blocking request runs in an
executor via urllib (which has HTTPDigestAuthHandler).  The bridge uses a
self-signed certificate, so TLS verification is disabled for it.
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORM_SENSOR = "sensor"
PLATFORM_BINARY_SENSOR = "binary_sensor"

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


class Plan44WebApiError(Exception):
    """Raised when the web API cannot be queried."""


class Plan44WebApi:
    """Minimal async wrapper around the plan44 web vdc JSON API."""

    def __init__(
        self, hass: HomeAssistant, base_url: str, user: str, password: str
    ) -> None:
        self._hass = hass
        self._base = base_url.rstrip("/")
        self._user = user
        self._password = password

    async def async_list_devices(self) -> list[DiscoveredDevice]:
        payload = await self._hass.async_add_executor_job(
            self._request_sync, _DESCRIPTIONS_QUERY
        )
        return parse_devices(payload)

    async def async_get_states(
        self, dsuids: set[str]
    ) -> dict[str, dict[str, dict[str, Any]]]:
        payload = await self._hass.async_add_executor_job(
            self._request_sync, _STATES_QUERY
        )
        return parse_states(payload, dsuids)

    async def async_validate(self) -> None:
        """Raise Plan44WebApiError if the API is not reachable/usable."""
        await self._hass.async_add_executor_job(self._request_sync, _DESCRIPTIONS_QUERY)

    # -- blocking implementation (runs in executor) ------------------------

    def _request_sync(self, query: dict[str, Any]) -> Any:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        pwmgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        pwmgr.add_password(None, self._base, self._user, self._password)
        opener = urllib.request.build_opener(
            urllib.request.HTTPDigestAuthHandler(pwmgr),
            urllib.request.HTTPSHandler(context=ctx),
        )

        token: Any = None
        try:
            with opener.open(self._base + "/tok/json", timeout=15) as tr:
                token = json.loads(tr.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            if err.code != 404:
                raise Plan44WebApiError(f"token request failed: {err}") from err
        except OSError as err:
            raise Plan44WebApiError(f"cannot reach {self._base}: {err}") from err

        endpoint = self._base + "/api/json/vdc"
        if token not in (None, True, False):
            endpoint += "?rqvaltok=" + urllib.parse.quote(str(token))

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(query).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            with opener.open(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (OSError, json.JSONDecodeError) as err:
            raise Plan44WebApiError(f"vdc API request failed: {err}") from err


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
                        "sensorStates": None,
                        "binaryInputStates": None,
                    }
                }
            }
        }
    },
}


def _iter_devices(payload: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if "dSUID" in node and (
                "sensorDescriptions" in node
                or "binaryInputDescriptions" in node
                or "sensorStates" in node
                or "binaryInputStates" in node
            ):
                found.append(node)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(payload)
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


def parse_states(
    payload: Any, dsuids: set[str]
) -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {}
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
        result[dsuid] = {PLATFORM_SENSOR: sensors, PLATFORM_BINARY_SENSOR: inputs}
    return result
