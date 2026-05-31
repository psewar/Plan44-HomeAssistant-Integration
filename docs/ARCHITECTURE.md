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
| `coordinator.py` | export (HA → P44) + the inbound push callback registry/dispatch |
| `state_mapping.py` | pure HA-state → core-state conversion (export) |
| `web_client.py` | read-only REST client for the web vdc JSON API (import: list devices + read states) |
| `device_coordinator.py` | `DataUpdateCoordinator` that polls imported device states |
| `device_templates.py` | built-in EnOcean device profiles + custom-channel helper |
| `inbound.py` | resolves a `p44_device` subentry to (tag, name, channels) |
| `sensor.py` / `binary_sensor.py` | poll-backed (REST) and push-backed entities |

## Two data paths

### Export — Home Assistant → plan44

HA entity state changes are converted by `state_mapping.ha_state_to_core` and sent
over the TCP external device API (port 8999) by `plan44_client` / `coordinator`.

### Import — plan44 → Home Assistant

Physical bridge devices are read over the bridge's **web vdc JSON API**
(`POST <web_url>/api/json/vdc`, HTTP Digest, self-signed TLS accepted):

1. The config flow calls `web_client.async_list_devices()` to populate the device
   picker and derive HA channel specs from each device's `sensorDescriptions` /
   `binaryInputDescriptions`.
2. `device_coordinator` polls `web_client.async_get_states()` for all imported
   dSUIDs on an interval.
3. `Plan44RestSensor` / `Plan44RestBinarySensor` read their value from the
   coordinator by `(dSUID, channel key)`.

A second, push-based inbound path exists (`coordinator.dispatch_inbound_channel`
keyed by `(message, tag, index)`) for the manual/template subentry case, but
physical devices do not push to the external API, so the REST poll above is the
path that surfaces live values.

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
