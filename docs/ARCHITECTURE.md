# Architecture and protocol notes

## High-level structure

The repository contains two layers.

### `plan44_core`

The core handles:

- device models
- protocol message creation
- incoming message parsing
- the raw TCP session to P44
- the live test harness

This is the main source of truth for the plan44 protocol mapping.

### `custom_components/plan44`

The Home Assistant integration acts as the adapter around the core. It handles:

- Config Flow / Options Flow and config subentries (two types: `virtual_device`
  for export, `p44_device` for import)
- storage and mapping persistence
- Home Assistant services
- conversion between Home Assistant entities and core device/state models
- the `sensor` and `binary_sensor` platforms for imported devices

Key modules:

| Module | Role |
|--------|------|
| `coordinator.py` | export (HA → P44) + tag-based inbound control-back for exported devices + connection state |
| `state_mapping.py` | pure HA-state → core-state conversion (export) |
| `web_client.py` | REST client for the web vdc JSON API (device discovery, poll states, set channels) |
| `device_coordinator.py` | `DataUpdateCoordinator` that polls imported device states from the web vdc JSON API |
| `device_templates.py` | built-in EnOcean device profiles + custom-channel helper |
| `inbound.py` | resolves a `p44_device` subentry to (tag, name, channels) |
| `light.py` | imported light entity (`Plan44RestLight`); state polled via `device_coordinator` |
| `sensor.py` / `binary_sensor.py` | poll-backed (REST, imported devices) and tag-based inbound (exported/manual) entities |

## Two data paths

### Export — Home Assistant → plan44

HA entity state changes are converted by `state_mapping.ha_state_to_core` and sent
over the TCP external device API (port 8999) by `plan44_client` / `coordinator`.

### Import — plan44 → Home Assistant

Device discovery and first-time setup use the bridge's **web vdc JSON API**
(`POST https://<host>/api/json/vdc`, HTTP Digest, self-signed TLS accepted):

1. The config flow calls `web_client.async_list_light_devices()` /
   `async_list_devices()` to populate the device picker and derive HA channel
   specs from `channelDescriptions` / `sensorDescriptions` /
   `binaryInputDescriptions`.

#### Imported device states — polling

Imported (dSUID-based) devices are **polled**: `device_coordinator` reads their
state from the web vdc JSON API at the configured interval.

- Light output devices: `web_client.async_get_light_states()` returns the current
  channel values.
- Sensor / binary_sensor devices: `web_client.async_get_states()` returns the
  current sensor values and binary-input states.

The external device API (port 8999) does **not** push foreign device state: the
bridge routes those events to the digitalSTROM vdSM, not to the external device
API. An earlier `subscribe`-based push path was removed in v0.7.8 after live
testing on the bridge confirmed the subscription is rejected
(`no device tagged '' found`) and no `channelStates` / `sensorStates` /
`binaryInputStates` events are delivered. Imported devices are therefore
poll-only, and the poll interval bounds the worst-case update latency.

#### Tag-based inbound — exported and manual devices

The tag-based inbound path (`coordinator.dispatch_inbound_channel` keyed by
`(message, tag, index)`) handles control-back for devices HA registers on the
bridge over the external device API — exported entities and manual/tag-based
subentries. For those the bridge sends `channel` / `sensor` / `input` messages
addressed to the device's tag. (Physical devices imported via the web-API picker
do not use this path — see [DEVICE_IMPORT.md](DEVICE_IMPORT.md).)

## Verified mappings

### Actuators

- `switch` -> P44 `output: "light"`
- `light` -> P44 `output: "light"`

### Sensors / inputs

- `sensor` -> `protocol: "simple"` with `sensors: [...]`
- `binary_sensor` -> input device with `inputs: [...]`

## Why `switch` is mapped as `output: "light"`

This was verified against a real P44 bridge.

Using `output: "switch"` led to runtime errors when channel `0` values were sent.
Using `output: "light"` worked correctly for simple on/off behavior with values `0` and `100`.

## Why `binary_sensor` is modeled as an input device

`binary_sensor` is not an actuator. For P44, the better model is an input definition via `inputs: [...]` and state updates sent via `message: "input"`.

This was also verified against a real P44 bridge.

## Source of truth

When in doubt, treat these as the authoritative references in this order:

1. live tests in `tests/live`
2. protocol code in `plan44_core`
3. Home Assistant adapter layer in `custom_components/plan44`
4. written documentation
