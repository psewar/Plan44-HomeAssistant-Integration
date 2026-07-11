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
| `coordinator.py` | export (HA → P44) + inbound push callback registry + push routing for all dSUID event types |
| `state_mapping.py` | pure HA-state → core-state conversion (export) |
| `web_client.py` | REST client for the web vdc JSON API (device discovery, poll states, set channels); `parse_push_*` helpers shared with push path |
| `device_coordinator.py` | `DataUpdateCoordinator` that polls imported device states; `async_apply_push_channel_states` and `async_apply_push_sensor_states` for instant push updates |
| `device_templates.py` | built-in EnOcean device profiles + custom-channel helper |
| `inbound.py` | resolves a `p44_device` subentry to (tag, name, channels) |
| `light.py` | push-backed light entity (`Plan44RestLight`); push via coordinator, poll via `device_coordinator` |
| `sensor.py` / `binary_sensor.py` | poll-backed (REST) and push-backed (tag-based) entities |

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

#### Light output devices — push path (primary)

After the TCP connection is established, `coordinator._async_subscribe_push()`
sends `{"message": "subscribe", "events": ["channelStates"]}` to the bridge.
When any output device changes state, the bridge sends:

```json
{"message": "channelStates", "dSUID": "...", "channelStates": {"brightness": {"value": 80.0}, ...}}
```

`coordinator.async_handle_plan44_message()` intercepts dSUID-based messages and
calls `device_coordinator.async_apply_push_channel_states()`, which parses the
payload via `web_client.parse_push_light_channel_states()`, updates
`coordinator.data` in-place, and immediately fires all registered entity
listeners — no HTTP round-trip.

`device_coordinator` continues polling `web_client.async_get_light_states()` at
the configured interval as a fallback for robustness.

#### Sensor / binary_sensor devices — push path (primary)

`coordinator._async_subscribe_push()` also subscribes to `sensorStates` and
`binaryInputStates` events.  When the bridge sends a notification for a known
imported sensor device, `async_handle_plan44_message()` calls
`device_coordinator.async_apply_push_sensor_states()`, which merges the pushed
values into the per-device state dict via `web_client.parse_push_sensor_states()`
and immediately fires all registered entity listeners.

`device_coordinator` continues polling `web_client.async_get_states()` at the
configured interval as a fallback — for robustness and for devices with slow
natural update intervals.

A separate, push-based inbound path (`coordinator.dispatch_inbound_channel`
keyed by `(message, tag, index)`) exists for the manual/tag-based subentry case
where the user registers a physical device as a virtual device tag.

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
