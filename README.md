# plan44 for Home Assistant

`plan44` is a custom Home Assistant integration that bridges Home Assistant and a
plan44 (P44-DSB / P44-LC) bridge in **both directions**:

- **Export (Home Assistant → plan44):** publish selected HA entities to plan44 as
  virtual devices.
- **Import (plan44 → Home Assistant):** bring physical devices registered on the
  bridge (e.g. EnOcean sensors that digitalSTROM does not expose) into HA as
  `sensor` / `binary_sensor` entities.

## What it does

This integration complements an existing digitalSTROM → Home Assistant
integration. A typical setup:

- digitalSTROM / dSS → existing HA integration
- Home Assistant → `plan44` → plan44 (export of HA entities)
- plan44 → `plan44` → Home Assistant (import of physical devices digitalSTROM
  doesn't surface, e.g. motion/acceleration)

## Current scope

**Export (HA → plan44):**

- bidirectional control for `switch` and `light` (on/off + brightness)
- forward export for `sensor` and `binary_sensor`
- reconnect and republish logic, loop protection for reverse commands
- reconfigure flow for changing host/port/model without deleting the config entry
- diagnostics and system health support

**Import (plan44 → HA):**

- pick a physical device from a live dropdown read from the bridge web API
- channels (units, device classes) are derived automatically from the device's
  own descriptions and grouped as one HA device
- values are read by polling the web vdc JSON API
- built-in EnOcean device profiles plus a manual fallback; see
  [Importing plan44 devices](docs/DEVICE_IMPORT.md)

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
4. **To export HA entities:** add them as virtual devices from the `plan44`
   integration UI (**+ Add virtual device**). For YAML-managed helper/template
   entities, see [Home Assistant YAML structure](docs/HOME_ASSISTANT_YAML.md).
5. **To import bridge devices:** add the web API URL + login in the integration
   options, then use **+ Import P44 device** to pick a device. See
   [Importing plan44 devices](docs/DEVICE_IMPORT.md).


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
- [Importing plan44 devices into Home Assistant](docs/DEVICE_IMPORT.md)
- [Creating and managing virtual devices](docs/VIRTUAL_DEVICES.md)
- [Home Assistant YAML structure for virtual devices](docs/HOME_ASSISTANT_YAML.md)
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

Then run the checks:

```bash
ruff check .
ruff format --check .
pyright
pytest tests/unit -q                 # core/protocol unit tests
pytest -c pytest.ha.ini -q           # Home Assistant component tests (Linux/WSL only)
```

The Home Assistant component tests require Linux (the HA test tooling imports
POSIX-only modules such as `fcntl`); on Windows run them under WSL. CI runs all
of the above. For live P44 tests and more detail, see
[Testing and live verification](docs/TESTING.md).

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
