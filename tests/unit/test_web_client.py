"""Unit tests for the plan44 web API parsing/mapping (no Home Assistant needed)."""

from __future__ import annotations

import ssl
from typing import Any

import pytest

from custom_components.plan44.web_client import (
    PLATFORM_BINARY_SENSOR,
    PLATFORM_SENSOR,
    LightChannelState,
    build_ssl_context,
    default_web_url,
    fetch_server_cert_pem,
    parse_devices,
    parse_light_devices,
    parse_light_states,
    parse_states,
)

# Throwaway self-signed certificate, only used to prove the pinned TLS context
# trusts exactly this cert (CERT_REQUIRED). It is not used to reach anything.
_TEST_CERT_PEM = """-----BEGIN CERTIFICATE-----
MIIDDTCCAfWgAwIBAgIUdmpJaDpcs7UBseH/jevVPF3O3EQwDQYJKoZIhvcNAQEL
BQAwFjEUMBIGA1UEAwwLcGxhbjQ0LXRlc3QwHhcNMjYwNjA4MjM1MjM1WhcNMzYw
NjA1MjM1MjM1WjAWMRQwEgYDVQQDDAtwbGFuNDQtdGVzdDCCASIwDQYJKoZIhvcN
AQEBBQADggEPADCCAQoCggEBALCvCNqFTzLieo3745dOWGTldrmjyYGQifWURKnn
4k4E9qAfOTutcGbJwXn8d0fcNTa2yueUXX7cyHasR1CaWdTFHJ1nsc78I12zBP5k
h3p5j6Foc4ROT/HMXw49H4PeI+fKxuQSZehgEtLYj2dK+4ebIOeiMsfDfuhh0n5f
4RbO42i7s5R0MQB4drZxI8M5CDEErcFFsO3iyC8ULoNFJQgZd2/jNh9QJMO0ySku
NtLmI3ohAFOp48aTwgjQhDQ9hf5wd+ZgwffFL8fk10b+DTCJVdFBBD0V3AGfRY6l
2LjrVhYgkGpZZUPmS+m9fXk7PTiaUYu+7Uqnv4mNU3GjecECAwEAAaNTMFEwHQYD
VR0OBBYEFCSiripl53BfOZpc0YT8MPtMfRPPMB8GA1UdIwQYMBaAFCSiripl53Bf
OZpc0YT8MPtMfRPPMA8GA1UdEwEB/wQFMAMBAf8wDQYJKoZIhvcNAQELBQADggEB
AHotD75QsVLffbEsnFK33+QnqYLPCMZC9M8Ch9Jaxpp0fRs/829g3cMRgqgYy9u7
NVDWtn97WoNZTewxg59eUMdpSqUXktEE+QpI9N/60T0MxyQUvP90FLRguXw4r0H4
mVul8vpdCj8CI2y3TayfKVlt1R5y3E4vc3cRePW4O49GqsLGXBCMNxZdu1jWPjpb
X5XigEOQfM3PkXplxuOx5sXXx4+PCQLppP+BYSRtpaDN2X1sY0YYEsade8NbTZU+
7sgPInDWni1TdvbEx40cuqhNnA16/2NIifnBWj8/fDk9T2rfWweOti545Mj7g7m3
NV3gatAu5eveukeueUYtcxM=
-----END CERTIFICATE-----
"""


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("plan44.local", "https://plan44.local"),
        ("192.0.2.50", "https://192.0.2.50"),
        ("  plan44.local  ", "https://plan44.local"),
        ("https://plan44.local", "https://plan44.local"),
        ("https://plan44.local/", "https://plan44.local"),
        ("http://192.0.2.50", "http://192.0.2.50"),
        (None, None),
        ("", None),
        ("   ", None),
    ],
)
def test_default_web_url(host: str | None, expected: str | None) -> None:
    assert default_web_url(host) == expected


def _payload(devices: list[dict[str, Any]]) -> dict[str, Any]:
    """Wrap devices in the x-p44-vdcs/x-p44-devices envelope."""
    return {
        "result": {
            "x-p44-vdcs": {
                "vdc0": {"x-p44-devices": {str(i): d for i, d in enumerate(devices)}}
            }
        }
    }


def test_parse_devices_maps_units_and_classes() -> None:
    payload = _payload(
        [
            {
                "dSUID": "AAA",
                "name": "Valve",
                "model": "Micropelt (A5-20-06)",
                "sensorDescriptions": {
                    "temperature": {"sensorType": 1, "siunit": "celsius"},
                    "set_point": {"sensorType": 11, "siunit": "none"},
                },
                "binaryInputDescriptions": {
                    "low_battery": {"sensorFunction": 12},
                },
            }
        ]
    )
    devices = parse_devices(payload)
    assert len(devices) == 1
    dev = devices[0]
    assert dev.dsuid == "AAA"
    assert dev.name == "Valve"
    by_key = {c.key: c for c in dev.channels}

    temp = by_key["temperature"]
    assert temp.platform == PLATFORM_SENSOR
    assert temp.unit == "°C"
    assert temp.device_class == "temperature"
    assert temp.state_class == "measurement"

    sp = by_key["set_point"]
    assert sp.unit is None
    assert sp.device_class is None

    bat = by_key["low_battery"]
    assert bat.platform == PLATFORM_BINARY_SENSOR
    assert bat.device_class == "battery"


def test_parse_devices_energy_is_total_increasing() -> None:
    payload = _payload(
        [
            {
                "dSUID": "P",
                "name": "Plug",
                "model": "",
                "sensorDescriptions": {
                    "energy": {"sensorType": 16, "siunit": "kilowatthour"},
                    "power": {"sensorType": 14, "siunit": "watt"},
                },
            }
        ]
    )
    by_key = {c.key: c for c in parse_devices(payload)[0].channels}
    assert by_key["energy"].unit == "kWh"
    assert by_key["energy"].device_class == "energy"
    assert by_key["energy"].state_class == "total_increasing"
    assert by_key["power"].device_class == "power"


def test_parse_devices_skips_channelless() -> None:
    payload = _payload([{"dSUID": "X", "name": "Light", "model": "Hue"}])
    assert parse_devices(payload) == []


def test_parse_devices_unknown_type_is_plain_sensor() -> None:
    payload = _payload(
        [
            {
                "dSUID": "U",
                "name": "Odd",
                "model": "",
                "sensorDescriptions": {"weird": {"sensorType": 999, "siunit": "xyz"}},
            }
        ]
    )
    ch = parse_devices(payload)[0].channels[0]
    assert ch.platform == PLATFORM_SENSOR
    assert ch.device_class is None
    assert ch.unit is None  # unknown siunit
    assert ch.state_class == "measurement"


def test_parse_states_filters_and_extracts() -> None:
    payload = _payload(
        [
            {
                "dSUID": "AAA",
                "sensorStates": {"temperature": {"value": 21.5}},
                "binaryInputStates": {"low_battery": {"value": False}},
            },
            {
                "dSUID": "BBB",
                "sensorStates": {"temperature": {"value": 9.9}},
            },
        ]
    )
    states = parse_states(payload, {"AAA"})
    assert set(states) == {"AAA"}  # BBB filtered out
    assert states["AAA"][PLATFORM_SENSOR]["temperature"] == 21.5
    assert states["AAA"][PLATFORM_BINARY_SENSOR]["low_battery"] is False


def test_parse_states_missing_value_is_none() -> None:
    payload = _payload([{"dSUID": "AAA", "sensorStates": {"temperature": {}}}])
    states = parse_states(payload, {"AAA"})
    assert states["AAA"][PLATFORM_SENSOR]["temperature"] is None


# ---------------------------------------------------------------------------
# parse_light_devices
# ---------------------------------------------------------------------------


def _hue_full_color_device(dsuid: str = "LGT01") -> dict[str, Any]:
    return {
        "dSUID": dsuid,
        "name": "HueIris Kay",
        "model": "Extended color light",
        "outputSettings": {"mode": 2, "colorClass": 1},
        "channelDescriptions": {
            "brightness": {"min": 0.0, "max": 100.0},
            "hue": {"min": 0.0, "max": 360.0},
            "saturation": {"min": 0.0, "max": 100.0},
            "colortemp": {"min": 153.0, "max": 500.0},
            "x": {"min": 0.0, "max": 1.0},
            "y": {"min": 0.0, "max": 1.0},
        },
    }


def _hue_ct_only_device(dsuid: str = "LGT02") -> dict[str, Any]:
    return {
        "dSUID": dsuid,
        "name": "HueAmbiance",
        "model": "Color temperature light",
        "outputSettings": {"mode": 2},
        "channelDescriptions": {
            "brightness": {"min": 0.0, "max": 100.0},
            "colortemp": {"min": 153.0, "max": 454.0},
        },
    }


def test_parse_light_devices_full_color() -> None:
    payload = _payload([_hue_full_color_device()])
    devices = parse_light_devices(payload)
    assert len(devices) == 1
    dev = devices[0]
    assert dev.dsuid == "LGT01"
    assert dev.name == "HueIris Kay"
    assert dev.model == "Extended color light"
    assert dev.has_color_temp is True
    assert dev.has_hs_color is True
    assert dev.color_temp_min_mired == 153.0
    assert dev.color_temp_max_mired == 500.0


def test_parse_light_devices_color_temp_only() -> None:
    payload = _payload([_hue_ct_only_device()])
    devices = parse_light_devices(payload)
    assert len(devices) == 1
    dev = devices[0]
    assert dev.has_color_temp is True
    assert dev.has_hs_color is False
    assert dev.color_temp_min_mired == 153.0
    assert dev.color_temp_max_mired == 454.0


def test_parse_light_devices_skips_no_brightness() -> None:
    payload = _payload(
        [
            {
                "dSUID": "NOPE",
                "name": "Switch",
                "outputSettings": {"mode": 0},
                "channelDescriptions": {"relay": {"min": 0.0, "max": 1.0}},
            }
        ]
    )
    assert parse_light_devices(payload) == []


def test_parse_light_devices_skips_no_output_settings() -> None:
    payload = _payload(
        [
            {
                "dSUID": "NOPE",
                "name": "Sensor",
                "channelDescriptions": {"brightness": {"min": 0.0, "max": 100.0}},
            }
        ]
    )
    assert parse_light_devices(payload) == []


def test_parse_light_devices_multiple() -> None:
    payload = _payload([_hue_full_color_device("LGT01"), _hue_ct_only_device("LGT02")])
    devices = parse_light_devices(payload)
    assert len(devices) == 2
    dsuids = {d.dsuid for d in devices}
    assert dsuids == {"LGT01", "LGT02"}


# ---------------------------------------------------------------------------
# parse_light_states
# ---------------------------------------------------------------------------


def _state_payload(devices: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "result": {
            "x-p44-vdcs": {
                "vdc0": {"x-p44-devices": {str(i): d for i, d in enumerate(devices)}}
            }
        }
    }


def _full_color_state(dsuid: str = "LGT01") -> dict[str, Any]:
    return {
        "dSUID": dsuid,
        "channelDescriptions": {"brightness": {}},
        "channelStates": {
            "brightness": {"value": 80.0},
            "colortemp": {"value": 250.0},
            "hue": {"value": 120.0},
            "saturation": {"value": 100.0},
        },
    }


def test_parse_light_states_full() -> None:
    payload = _state_payload([_full_color_state()])
    states = parse_light_states(payload, {"LGT01"})
    assert set(states) == {"LGT01"}
    ls = states["LGT01"]
    assert isinstance(ls, LightChannelState)
    assert ls.brightness == 80.0
    assert ls.color_temp_mired == 250.0
    assert ls.hue == 120.0
    assert ls.saturation == 100.0


def test_parse_light_states_filters_by_dsuid() -> None:
    payload = _state_payload([_full_color_state("LGT01"), _full_color_state("LGT02")])
    states = parse_light_states(payload, {"LGT01"})
    assert set(states) == {"LGT01"}


def test_parse_light_states_missing_optional_channels() -> None:
    payload = _state_payload(
        [
            {
                "dSUID": "LGT03",
                "channelDescriptions": {"brightness": {}},
                "channelStates": {"brightness": {"value": 50.0}},
            }
        ]
    )
    states = parse_light_states(payload, {"LGT03"})
    ls = states["LGT03"]
    assert ls.brightness == 50.0
    assert ls.color_temp_mired is None
    assert ls.hue is None
    assert ls.saturation is None


def test_parse_light_states_skips_no_brightness() -> None:
    payload = _state_payload(
        [
            {
                "dSUID": "LGT04",
                "channelDescriptions": {"brightness": {}},
                "channelStates": {"colortemp": {"value": 300.0}},
            }
        ]
    )
    states = parse_light_states(payload, {"LGT04"})
    assert states == {}


def test_ssl_context_unpinned_disables_verification() -> None:
    """Before a cert is pinned we fall back to no verification."""
    ctx = build_ssl_context(None)
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False


def test_ssl_context_pinned_requires_certificate() -> None:
    """With a pinned cert the context verifies the peer against exactly it."""
    ctx = build_ssl_context(_TEST_CERT_PEM)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is False


def test_fetch_server_cert_pem_handles_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unreachable bridge yields None (caller keeps working unpinned)."""

    def _boom(*_args: Any, **_kwargs: Any) -> str:
        raise OSError("connection refused")

    monkeypatch.setattr(ssl, "get_server_certificate", _boom)
    assert fetch_server_cert_pem("https://192.0.2.50") is None


def test_fetch_server_cert_pem_rejects_unparseable_url() -> None:
    assert fetch_server_cert_pem("not-a-url") is None


def test_parse_devices_survives_pathological_nesting() -> None:
    """A deeply nested payload must not blow the recursion stack."""
    deep: dict[str, Any] = {}
    cur = deep
    for _ in range(2000):  # well beyond the interpreter's recursion limit
        nxt: dict[str, Any] = {}
        cur["n"] = nxt
        cur = nxt
    assert parse_devices(deep) == []  # guard stops early; no RecursionError
