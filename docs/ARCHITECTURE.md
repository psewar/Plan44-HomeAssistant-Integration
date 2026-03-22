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

### `custom_components/plan44_integration`

The Home Assistant integration acts as a thin adapter around the core.

It handles:

- Config Flow
- Options Flow
- storage and mapping persistence
- Home Assistant services
- conversion between Home Assistant entities and core device/state models

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
3. Home Assistant adapter layer in `custom_components/plan44_integration`
4. written documentation
