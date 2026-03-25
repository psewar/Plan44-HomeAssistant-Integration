# plan44 for Home Assistant

`plan44` is a custom Home Assistant integration that exports selected Home Assistant entities to plan44 as virtual devices.

## What it does

This integration is intended to complement an existing digitalSTROM to Home Assistant integration.

Recommended setup:

- digitalSTROM / dSS -> existing HA integration
- Home Assistant -> `plan44` -> plan44 -> digitalSTROM

This keeps `plan44` focused on the Home Assistant -> plan44 path.

## Current scope

Version 1 focuses on:

- Home Assistant -> plan44 export
- bidirectional control for:
  - `switch`
  - `light` (on/off + brightness)
- forward export for:
  - `sensor`
  - `binary_sensor`
- reconnect and republish logic
- loop protection for reverse commands
- reconfigure flow for changing host/port/model without deleting the config entry
- diagnostics and system health support

## Live-verified device matrix

The following mappings have been verified against a real P44 bridge:

- `switch` -> P44 `output: "light"` with channel `index: 0` and values `0/100`
- `light` -> P44 `output: "light"` with channel `index: 0` and brightness mapped to `0..100`
- `sensor` -> P44 `protocol: "simple"` with `sensors: [...]` and updates via `message: "sensor"`
- `binary_sensor` -> P44 input device with `inputs: [...]` and updates via `message: "input"`

## Supported entity types

### Bidirectional
- `switch`
- `light`

### Forward only
- `sensor`
- `binary_sensor`

## Quick start

1. Install the custom integration.
2. Add `plan44` via the Home Assistant UI.
3. Enter the P44 host, port, and VDC model name.
4. Create or choose Home Assistant entities that you want to expose to plan44. For YAML-managed helper/template entities, see [Home Assistant YAML structure for virtual devices](docs/HOME_ASSISTANT_YAML.md).
5. Add those entities as virtual devices from the `plan44` integration UI.


## Home Assistant YAML helpers

If you want to define helper and template entities for `plan44`, add a packages folder to your Home Assistant configuration and include it from `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

A good default is to maintain your plan44-related entities in:

```text
/config/packages/plan44_virtual_devices.yaml
```

See [docs/HOME_ASSISTANT_YAML.md](docs/HOME_ASSISTANT_YAML.md) for examples.

## Documentation

- [Configuration and setup](docs/CONFIGURATION.md)
- [Configuration and setup](docs/CONFIGURATION.md)
- [Home Assistant YAML structure for virtual devices](docs/HOME_ASSISTANT_YAML.md)
- [Creating and managing virtual devices](docs/VIRTUAL_DEVICES.md)
- [Testing and live verification](docs/TESTING.md)
- [Architecture and protocol notes](docs/ARCHITECTURE.md)

## UI-first management

The preferred way to manage exported devices is now the `plan44` integration UI.

Use the UI to:

- add a virtual device
- edit a virtual device
- remove a virtual device

The legacy services still exist for compatibility and automation use cases, but the recommended daily workflow is documented in [Creating and managing virtual devices](docs/VIRTUAL_DEVICES.md).

## Legacy services

- `plan44.create_virtual_device`
- `plan44.remove_virtual_device`
- `plan44.republish_virtual_devices`
- `plan44.push_entity_state`

## Preventing loops

This integration is intended to export manually selected Home Assistant entities to plan44.

Be careful when exporting entities that already originate from digitalSTROM or another bridge path.
To reduce feedback loops, the integration supports:

- blocked integrations
- blocked entity ID prefixes
- reverse command suppression cooldown
- forward state suppression cooldown

For safety, start with manually selected entities only.

## Runtime baseline

- Python **3.14.3** is the supported baseline for this repository.
- The code is intentionally optimized for current Python and current Home Assistant test tooling.
- Older Python compatibility shims have been removed.

## Development quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
pip install -r requirements_ha_test.txt
pip install -e .
```

Then run:

```bash
pyright
ruff check .
pytest tests/unit -q
```

For live P44 tests, see [Testing and live verification](docs/TESTING.md).

## Notes

This repository is still evolving. The most reliable source of truth for supported device mappings is the combination of:

- the code in `plan44_core`
- the live P44 tests under `tests/live`
- the documentation in the `docs/` folder


## Repository checks

Before committing, run one of these from the repository root:

```bash
./precommit_check.sh
```

On PowerShell:

```powershell
./precommit_check.ps1
```
