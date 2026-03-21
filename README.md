# plan44 Integration for Home Assistant

`plan44_integration` is a custom Home Assistant integration that exports selected Home Assistant entities to plan44 as virtual devices.

## Current scope

Version 1 focuses on:

- Home Assistant -> plan44 export
- bidirectional control for:
  - `switch`
  - `light` (on/off + brightness mapping)
- forward export for:
  - `sensor`
  - `binary_sensor`
- reconnect and republish logic
- loop protection for reverse commands
- reconfigure flow for changing host/port/model without deleting the config entry
- diagnostics and system health support

## Intended architecture

This integration is designed to complement an existing digitalSTROM -> Home Assistant integration.

Recommended setup:

- digitalSTROM / dSS -> existing HA integration
- Home Assistant -> `plan44_integration` -> plan44 -> digitalSTROM

This avoids rebuilding digitalSTROM discovery and keeps this integration focused on the Home Assistant -> plan44 path.

## Features

- Config Flow for plan44 connection setup
- Reconfigure Flow for host/port/VDC model updates
- Options Flow for runtime behavior
- Home Assistant services for:
  - `plan44_integration.create_virtual_device`
  - `plan44_integration.remove_virtual_device`
  - `plan44_integration.republish_virtual_devices`
  - `plan44_integration.push_entity_state`
- storage-backed export mapping
- reverse control from plan44 to Home Assistant for supported actuator types
- optional `entry_id` parameter in services when multiple config entries exist
- diagnostics and system health support

## Supported entity types

### Bidirectional
- `switch`
- `light`

### Forward only
- `sensor`
- `binary_sensor`

## Configuration

After installing the integration, add it via the Home Assistant UI.

Required settings:
- host
- port
- VDC model name

Optional settings:
- auto republish
- reverse control enabled
- reconnect interval
- blocked integrations
- blocked entity ID prefixes

## Services

### Create a virtual device

```yaml
service: plan44_integration.create_virtual_device
data:
  entity_id: switch.test_switch
  kind: switch
  name: Test Switch
  allow_reverse: true
```

When multiple plan44 config entries are configured, add `entry_id`.

```yaml
service: plan44_integration.create_virtual_device
data:
  entry_id: YOUR_CONFIG_ENTRY_ID
  entity_id: switch.test_switch
  kind: switch
  name: Test Switch
  allow_reverse: true
```

### Remove a virtual device

```yaml
service: plan44_integration.remove_virtual_device
data:
  entity_id: switch.test_switch
```

### Republish all virtual devices

```yaml
service: plan44_integration.republish_virtual_devices
```

### Push current entity state

```yaml
service: plan44_integration.push_entity_state
data:
  entity_id: switch.test_switch
```

## Preventing loops

This integration is intended to export manually selected Home Assistant entities to plan44.

Be careful when exporting entities that already originate from digitalSTROM or another bridge path.
To reduce feedback loops, the integration supports:

- blocked integrations
- blocked entity ID prefixes
- reverse command suppression cooldown
- forward state suppression cooldown

For safety, start with manually selected entities only.

## Development

### Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
```

### Run tests

```bash
pytest
```

### Run linting

```bash
ruff check .
ruff format --check .
```

## Roadmap

- reverse-path tests with more message variants
- improved management UI for exported entities
- optional P44 -> Home Assistant import path
- additional device classes
- finer-grained plan44 message handling

## Notes

This repository is an MVP foundation. plan44 message semantics may need refinement against a real target system.


## Running tests on Windows

`pytest-homeassistant-custom-component` imports parts of Home Assistant that expect
POSIX modules such as `fcntl`. Because of that, the test suite should be run in
**WSL, Docker, or another Linux environment**, not in native Windows Python.

Recommended local test setup on Windows:

- use WSL2 with Python 3.12 or 3.13
- or run the tests in a Linux container

The integration itself can still be edited on Windows; this limitation affects
mainly the Home Assistant test environment.


## plan44_core and live testing without Home Assistant

The repository also contains a HA-independent `plan44_core` package. It is intended for:

- protocol and mapping tests without Home Assistant
- live tests against a real plan44 bridge
- recording raw RX/TX traffic for device-type debugging

### Why this split exists

The Home Assistant integration should remain a thin adapter layer. The protocol and device-type behavior is easier to develop and regression-test in isolation.

### Core package structure

- `plan44_core.models`: generic device specs and states
- `plan44_core.protocol`: message building and reverse parsing
- `plan44_core.session`: TCP session to a real plan44 bridge
- `plan44_core.harness`: convenience wrapper for live tests and traces

### Live test configuration

Copy `devtools/.env.live.example` to `devtools/.env.live` and adjust the values.
That file is intentionally not committed.

Example:

```bash
cp devtools/.env.live.example devtools/.env.live
python devtools/run_live_tests.py
```

All traffic is written as JSONL to the configured trace path. This makes it easy to inspect exactly what was sent to and received from the real bridge.

### Running only the core unit tests

```bash
pytest tests/unit -vv
```

### Running live plan44 tests

```bash
python devtools/run_live_tests.py
```

These tests are skipped unless `P44_TEST_ENABLED=1` is set.
