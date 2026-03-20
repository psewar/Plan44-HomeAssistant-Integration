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
