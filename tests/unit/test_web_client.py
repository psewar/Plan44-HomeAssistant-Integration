"""Unit tests for the plan44 web API parsing/mapping (no Home Assistant needed)."""

from __future__ import annotations

import ssl
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.plan44.const import DEVICE_ACTIVE
from custom_components.plan44.web_client import (
    PLATFORM_BINARY_SENSOR,
    PLATFORM_SENSOR,
    DiscoveredLightDevice,
    LightChannelState,
    RadioState,
    build_ssl_context,
    default_web_url,
    fetch_server_cert_pem,
    parse_devices,
    parse_light_devices,
    parse_light_states,
    parse_push_light_channel_states,
    parse_radio_states,
    parse_states,
    steady_last_packet,
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
    assert isinstance(dev, DiscoveredLightDevice)
    assert dev.dsuid == "LGT01"
    assert dev.name == "HueIris Kay"
    assert dev.model == "Extended color light"
    assert dev.has_color_temp is True
    assert dev.has_hs_color is True
    assert dev.has_xy_color is True
    assert dev.color_temp_min_mired == 153.0
    assert dev.color_temp_max_mired == 500.0


def test_parse_light_devices_color_temp_only() -> None:
    payload = _payload([_hue_ct_only_device()])
    devices = parse_light_devices(payload)
    assert len(devices) == 1
    dev = devices[0]
    assert dev.has_color_temp is True
    assert dev.has_hs_color is False
    assert dev.has_xy_color is False
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
    # Real state-query responses have channelStates only (no channelDescriptions).
    return {
        "dSUID": dsuid,
        "channelStates": {
            "brightness": {"value": 80.0},
            "colortemp": {"value": 250.0},
            "hue": {"value": 120.0},
            "saturation": {"value": 100.0},
            "x": {"value": 0.172},
            "y": {"value": 0.747},
        },
    }


def test_parse_light_states_full() -> None:
    payload = _state_payload([_full_color_state()])
    states = parse_light_states(payload, {"LGT01"})
    assert set(states) == {"LGT01"}
    ls = states["LGT01"]["light"]
    assert isinstance(ls, LightChannelState)
    assert ls.brightness == 80.0
    assert ls.color_temp_mired == 250.0
    assert ls.hue == 120.0
    assert ls.saturation == 100.0
    assert ls.x == pytest.approx(0.172)
    assert ls.y == pytest.approx(0.747)


def test_parse_light_states_filters_by_dsuid() -> None:
    payload = _state_payload([_full_color_state("LGT01"), _full_color_state("LGT02")])
    states = parse_light_states(payload, {"LGT01"})
    assert set(states) == {"LGT01"}


def test_parse_light_states_without_channel_descriptions() -> None:
    # Regression: state-query responses have no channelDescriptions — nodes
    # must still be found by _iter_light_nodes.
    payload = _state_payload(
        [{"dSUID": "LGT05", "channelStates": {"brightness": {"value": 60.0}}}]
    )
    states = parse_light_states(payload, {"LGT05"})
    assert states["LGT05"]["light"].brightness == 60.0


def test_parse_light_states_missing_optional_channels() -> None:
    payload = _state_payload(
        [
            {
                "dSUID": "LGT03",
                "channelStates": {"brightness": {"value": 50.0}},
            }
        ]
    )
    states = parse_light_states(payload, {"LGT03"})
    ls = states["LGT03"]["light"]
    assert ls.brightness == 50.0
    assert ls.color_temp_mired is None
    assert ls.hue is None
    assert ls.saturation is None
    assert ls.x is None
    assert ls.y is None


def test_parse_light_states_skips_no_brightness() -> None:
    payload = _state_payload(
        [
            {
                "dSUID": "LGT04",
                "channelStates": {"colortemp": {"value": 300.0}},
            }
        ]
    )
    states = parse_light_states(payload, {"LGT04"})
    assert states == {}


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_channel_state_is_unavailable(bad: float) -> None:
    """NaN/Infinity must become None, not reach round()/Decimal downstream.

    json.loads accepts bare NaN/Infinity, and they pass a plain isinstance
    check — then raise inside a coordinator listener, costing every entity
    that would have been updated after the failing one.
    """
    # exercised through the public parser, not the private helper: a
    # non-finite brightness is treated exactly like a missing one.
    assert parse_push_light_channel_states({"brightness": {"value": bad}}) is None
    finite = parse_push_light_channel_states({"brightness": {"value": 42.0}})
    assert finite is not None and finite.brightness == 42.0


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


# ---------------------------------------------------------------------------
# parse_push_light_channel_states
# ---------------------------------------------------------------------------


def test_parse_push_light_channel_states_full() -> None:
    channel_states = {
        "brightness": {"value": 75.0},
        "colortemp": {"value": 280.0},
        "hue": {"value": 200.0},
        "saturation": {"value": 90.0},
        "x": {"value": 0.25},
        "y": {"value": 0.55},
    }
    ls = parse_push_light_channel_states(channel_states)
    assert ls is not None
    assert ls.brightness == 75.0
    assert ls.color_temp_mired == 280.0
    assert ls.hue == 200.0
    assert ls.saturation == 90.0
    assert ls.x == pytest.approx(0.25)
    assert ls.y == pytest.approx(0.55)


def test_parse_push_light_channel_states_no_brightness_returns_none() -> None:
    assert parse_push_light_channel_states({"colortemp": {"value": 300.0}}) is None


def test_parse_push_light_channel_states_brightness_only() -> None:
    ls = parse_push_light_channel_states({"brightness": {"value": 50.0}})
    assert ls is not None
    assert ls.brightness == 50.0
    assert ls.color_temp_mired is None
    assert ls.hue is None
    assert ls.x is None


def test_parse_devices_survives_pathological_nesting() -> None:
    """A deeply nested payload must not blow the recursion stack."""
    deep: dict[str, Any] = {}
    cur = deep
    for _ in range(2000):  # well beyond the interpreter's recursion limit
        nxt: dict[str, Any] = {}
        cur["n"] = nxt
        cur = nxt
    assert parse_devices(deep) == []  # guard stops early; no RecursionError


def test_parse_states_carries_the_active_flag() -> None:
    """The bridge's own verdict on whether a device still reports must survive.

    Without it a silent EnOcean device keeps its node in the poll (so the
    entity looks available) while every value is null — the entity then sits
    on "unknown" forever with nothing to distinguish it from a fresh start.
    """
    payload = {
        "result": {
            "x-p44-vdcs": {
                "v1": {
                    "x-p44-devices": {
                        "d1": {
                            "dSUID": "DEAD",
                            "active": False,
                            "sensorStates": {"temperature": {"value": None}},
                            "binaryInputStates": {},
                        },
                        "d2": {
                            "dSUID": "ALIVE",
                            "active": True,
                            "sensorStates": {"temperature": {"value": 21.5}},
                            "binaryInputStates": {},
                        },
                    }
                }
            }
        }
    }
    states = parse_states(payload, {"DEAD", "ALIVE"})
    assert states["DEAD"][DEVICE_ACTIVE] is False
    assert states["ALIVE"][DEVICE_ACTIVE] is True
    assert states["DEAD"]["sensor"]["temperature"] is None
    assert states["ALIVE"]["sensor"]["temperature"] == 21.5


def test_parse_states_without_active_field_has_no_opinion() -> None:
    """A bridge that omits `active` must not make everything unavailable."""
    payload = {
        "result": {
            "x-p44-vdcs": {
                "v1": {
                    "x-p44-devices": {
                        "d1": {
                            "dSUID": "OLD",
                            "sensorStates": {"temperature": {"value": 20.0}},
                        }
                    }
                }
            }
        }
    }
    assert parse_states(payload, {"OLD"})["OLD"][DEVICE_ACTIVE] is None


def test_light_states_carry_the_active_flag() -> None:
    """A lamp that is unreachable keeps its channel values; only active tells."""
    payload = _state_payload(
        [
            {
                "dSUID": "LGT09",
                "active": False,
                "channelStates": {"brightness": {"value": 80.0}},
            }
        ]
    )
    states = parse_light_states(payload, {"LGT09"})
    assert states["LGT09"][DEVICE_ACTIVE] is False
    # the stale value is still parsed — the flag is what makes it stale
    assert states["LGT09"]["light"].brightness == 80.0


def test_light_states_without_active_field_has_no_opinion() -> None:
    payload = _state_payload(
        [{"dSUID": "LGT10", "channelStates": {"brightness": {"value": 10.0}}}]
    )
    assert parse_light_states(payload, {"LGT10"})["LGT10"][DEVICE_ACTIVE] is None


def test_parse_light_devices_captures_the_real_vendor() -> None:
    """The bridge knows the actual manufacturer; plan44 is only the fallback."""
    payload = {
        "result": {
            "x-p44-vdcs": {
                "v1": {
                    "x-p44-devices": {
                        "d1": {
                            "dSUID": "LGT11",
                            "name": "Hue",
                            "model": "Extended color light",
                            "vendorName": "Signify Netherlands B.V.",
                            "outputSettings": {},
                            "channelDescriptions": {
                                "brightness": {"min": 0, "max": 100}
                            },
                        },
                        "d2": {
                            "dSUID": "LGT12",
                            "name": "Nameless",
                            "outputSettings": {},
                            "channelDescriptions": {
                                "brightness": {"min": 0, "max": 100}
                            },
                        },
                    }
                }
            }
        }
    }
    by_dsuid = {d.dsuid: d for d in parse_light_devices(payload)}
    assert by_dsuid["LGT11"].vendor == "Signify Netherlands B.V."
    # missing vendorName must not become the string "None"
    assert by_dsuid["LGT12"].vendor == ""


# ---------------------------------------------------------------------------
# parse_radio_states / steady_last_packet
# ---------------------------------------------------------------------------

# Device nodes shaped exactly as a P44-DSB-E2 (vdcd 2.8.4.6) answered the radio
# query, only names and dSUIDs replaced: a valve heard via one repeater, one the
# bridge has timed out and not heard since it started, a rocker that simply was
# not pressed, and a Hue lamp, which has no radio properties at all.
_RADIO_NOW = datetime(2026, 10, 24, 23, 32, 20, 476407, tzinfo=UTC)
_VALVE: dict[str, Any] = {
    "dSUID": "VALVE-A52006",
    "name": "MVA009 Living Room",
    "model": "Micropelt EnOcean heating valve actuator (A5-20-06)",
    "active": True,
    "x-p44-packetAge": 147.074148,
    "x-p44-rssi": -71,
    "x-p44-repeaterCount": 1,
    "x-p44-opStateText": "-71dBm1 Rep., ",
}
_TIMED_OUT_VALVE: dict[str, Any] = {
    "dSUID": "VALVE-A52001",
    "name": "MVA004 Office",
    "model": "Micropelt EnOcean heating valve actuator (A5-20-01)",
    "active": False,
    "x-p44-packetAge": None,
    "x-p44-rssi": None,
    "x-p44-repeaterCount": None,
    "x-p44-opStateText": "timeout, unseen",
}
_ROCKER: dict[str, Any] = {
    "dSUID": "ROCKER-F602",
    "name": "Hall rocker left",
    "model": "EnOcean rocker switch (F6-02-FF)",
    "active": True,
    "x-p44-packetAge": None,
    "x-p44-rssi": None,
    "x-p44-repeaterCount": None,
    "x-p44-opStateText": "unseen",
}
_HUE_LAMP: dict[str, Any] = {
    "dSUID": "HUE-LAMP",
    "name": "Sofa lamp",
    "model": "Extended color light: 4080248P9",
    "active": True,
    "x-p44-opStateText": "",
}


def test_parse_radio_states_picks_devices_that_report_a_packet_age() -> None:
    """Only radio devices carry the property; the lamp must not get radio entities."""
    payload = _state_payload([_VALVE, _TIMED_OUT_VALVE, _ROCKER, _HUE_LAMP])
    radio = parse_radio_states(payload, _RADIO_NOW)
    assert set(radio) == {
        str(_VALVE["dSUID"]),
        str(_TIMED_OUT_VALVE["dSUID"]),
        str(_ROCKER["dSUID"]),
    }


def test_parse_radio_states_turns_the_packet_age_into_a_timestamp() -> None:
    valve = parse_radio_states(_state_payload([_VALVE]), _RADIO_NOW)[
        str(_VALVE["dSUID"])
    ]
    assert valve == RadioState(
        dsuid=str(_VALVE["dSUID"]),
        name="MVA009 Living Room",
        model="Micropelt EnOcean heating valve actuator (A5-20-06)",
        active=True,
        # 23:32:20.48 minus 147.07 s, cut to the second
        last_packet=datetime(2026, 10, 24, 23, 29, 53, tzinfo=UTC),
        rssi=-71,
        repeater_count=1,
        has_repeater_count=True,
        op_state="-71dBm1 Rep., ",
    )


def test_parse_radio_states_unseen_device_has_no_timestamp() -> None:
    """No packet since the bridge started: no time can be claimed for it."""
    silent = parse_radio_states(_state_payload([_TIMED_OUT_VALVE]), _RADIO_NOW)[
        str(_TIMED_OUT_VALVE["dSUID"])
    ]
    assert silent.last_packet is None
    assert silent.rssi is None
    assert silent.repeater_count is None
    assert silent.has_repeater_count is True  # EnOcean has repeaters, none seen
    assert silent.active is False
    assert silent.op_state == "timeout, unseen"


def test_parse_radio_states_radio_without_repeaters() -> None:
    """ELDAT/ZF report age and RSSI but have no repeater property."""
    node = {
        "dSUID": "ELDAT1",
        "name": "Eldat",
        "active": True,
        "x-p44-packetAge": 30.0,
        "x-p44-rssi": -80,
    }
    eldat = parse_radio_states(_state_payload([node]), _RADIO_NOW)["ELDAT1"]
    assert eldat.has_repeater_count is False
    assert eldat.repeater_count is None
    assert eldat.rssi == -80
    assert eldat.op_state is None
    assert eldat.model == ""


@pytest.mark.parametrize(
    "field, bad",
    [
        ("x-p44-packetAge", -5.0),
        ("x-p44-packetAge", float("nan")),
        ("x-p44-packetAge", "147"),
        ("x-p44-rssi", float("inf")),
        ("x-p44-repeaterCount", "1"),
        ("active", "yes"),
        ("x-p44-opStateText", 42),
    ],
)
def test_parse_radio_states_rejects_implausible_values(field: str, bad: Any) -> None:
    """A malformed value becomes "unknown", not a crash or a made-up reading."""
    node = {**_VALVE, field: bad}
    valve = parse_radio_states(_state_payload([node]), _RADIO_NOW)[str(_VALVE["dSUID"])]
    parsed = {
        "x-p44-packetAge": valve.last_packet,
        "x-p44-rssi": valve.rssi,
        "x-p44-repeaterCount": valve.repeater_count,
        "active": valve.active,
        "x-p44-opStateText": valve.op_state,
    }
    assert parsed[field] is None


def _radio_at(last_packet: datetime | None) -> RadioState:
    return RadioState(
        dsuid="D1",
        name="Valve",
        model="",
        active=True,
        last_packet=last_packet,
        rssi=-70,
        repeater_count=0,
        has_repeater_count=True,
        op_state="-70dBm",
    )


_PACKET = datetime(2026, 10, 24, 23, 29, 53, tzinfo=UTC)


def test_steady_last_packet_keeps_the_timestamp_of_the_same_packet() -> None:
    """Poll latency must not move the timestamp (a state change every poll)."""
    jittered = _radio_at(_PACKET + timedelta(seconds=1))
    assert steady_last_packet(_radio_at(_PACKET), jittered).last_packet == _PACKET
    earlier = _radio_at(_PACKET - timedelta(seconds=2))
    assert steady_last_packet(_radio_at(_PACKET), earlier).last_packet == _PACKET


def test_steady_last_packet_takes_a_new_packet() -> None:
    newer = _radio_at(_PACKET + timedelta(minutes=2))
    assert steady_last_packet(_radio_at(_PACKET), newer) is newer


def test_steady_last_packet_follows_the_bridge_to_unseen() -> None:
    """After a bridge restart nothing is known any more; keep no stale time."""
    unseen = _radio_at(None)
    assert steady_last_packet(_radio_at(_PACKET), unseen).last_packet is None


def test_steady_last_packet_first_poll_and_other_fields() -> None:
    first = _radio_at(_PACKET)
    assert steady_last_packet(None, first) is first
    # Only the timestamp is held back; the rest of the poll passes through.
    stronger = replace(_radio_at(_PACKET + timedelta(seconds=1)), rssi=-60)
    steady = steady_last_packet(first, stronger)
    assert steady.last_packet == _PACKET
    assert steady.rssi == -60
