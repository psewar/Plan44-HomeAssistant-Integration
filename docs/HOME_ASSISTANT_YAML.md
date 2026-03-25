# Home Assistant YAML structure for `plan44`

This page explains where to put the helper entities and template entities that you want to export through `plan44`.

## Important clarification

These YAML files belong in your **Home Assistant configuration directory**, not in the `plan44` integration repository.

That means:

- if you installed `plan44` via HACS, you still create these files in your **HA config folder**
- you do **not** edit files inside `custom_components/plan44`
- you do **not** add files to the integration repository unless you are developing the integration itself

Typical Home Assistant config locations are:

- Home Assistant OS / Supervised: `/config`
- Home Assistant Container: the mounted config volume
- Home Assistant Core: the directory containing `configuration.yaml`

## Recommended approach

Home Assistant officially recommends **packages** if you want to keep all configuration for a subsystem together. Packages can bundle configuration from many integrations in one place, and the official docs explicitly recommend creating a `packages` folder and loading it from `configuration.yaml`. `!include_dir_named packages` is the most convenient approach because the package files keep the same indentation style as `configuration.yaml`, and Home Assistant notes that this method also supports YAML files in subfolders. citeturn324374view0turn324374view1

For `plan44`, the cleanest documented setup is:

- keep all `plan44` helper entities and template entities in a dedicated package file
- for example: `packages/plan44_virtual_devices.yaml`
- or, if you prefer a grouped structure: `packages/plan44/virtual_devices.yaml`

Both are valid with `!include_dir_named packages`, as long as package file names remain globally unique across the packages tree. Home Assistant's package docs call this out explicitly. citeturn324374view0

## Minimal recommended setup

### `configuration.yaml`

Add this under `homeassistant:`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

This is the officially documented package-folder approach. citeturn324374view0

### Directory structure

```text
/config
├── configuration.yaml
└── packages
    └── plan44_virtual_devices.yaml
```

### `packages/plan44_virtual_devices.yaml`

Example:

```yaml
input_boolean:
  plan44_test_switch_state:
    name: Plan44 Test Switch State

input_number:
  plan44_test_temperature_raw:
    name: Plan44 Test Temperature Raw
    min: 0
    max: 50
    step: 0.1

template:
  - switch:
      - name: "Plan44 Test Switch"
        unique_id: plan44_test_switch
        state: "{{ is_state('input_boolean.plan44_test_switch_state', 'on') }}"
        turn_on:
          - service: input_boolean.turn_on
            target:
              entity_id: input_boolean.plan44_test_switch_state
        turn_off:
          - service: input_boolean.turn_off
            target:
              entity_id: input_boolean.plan44_test_switch_state

    sensor:
      - name: "Plan44 Test Temperature"
        unique_id: plan44_test_temperature
        unit_of_measurement: "°C"
        state: "{{ states('input_number.plan44_test_temperature_raw') }}"
```

## Alternative grouped structure

If you want more structure, Home Assistant packages also support subfolders. The docs state that `!include_dir_named packages` loads YAML files in the packages folder **and its subfolders**. citeturn324374view0

Example:

```text
/config
├── configuration.yaml
└── packages
    └── plan44
        ├── helpers.yaml
        ├── sensors.yaml
        └── binary_sensors.yaml
```

In that setup, you still keep:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

The main thing to remember is that package file names must still be globally unique. For example, do not have two different files both named `helpers.yaml` in different subfolders. Home Assistant documents this requirement for `!include_dir_named packages`. citeturn324374view0

## When to use `!include_dir_merge_named`

Home Assistant also documents `!include_dir_merge_named`, but for packages it is usually less ergonomic because the package name must be present inside the file and indentation becomes less copy/paste friendly. The package docs explicitly point out that `!include_dir_named` is usually easier because it uses the same indentation style as `configuration.yaml`. citeturn324374view0

For most `plan44` users, the simplest and clearest option is therefore:

- `homeassistant: packages: !include_dir_named packages`
- one dedicated file such as `packages/plan44_virtual_devices.yaml`

## Good naming conventions

Recommended entity naming:

- `input_boolean.plan44_*`
- `input_number.plan44_*`
- `switch.plan44_*`
- `light.plan44_*`
- `sensor.plan44_*`
- `binary_sensor.plan44_*`

That makes it obvious which entities are intended to be exported through `plan44`.

## After you add or change YAML

If you add a new package file or change YAML-based entities/helpers:

- check the configuration in Home Assistant
- reload the affected YAML integrations if possible
- or restart Home Assistant if required

Then go back to the `plan44` integration UI and add the relevant source entities as virtual devices.


## Common mistake

The packages include must be nested under `homeassistant:`. This is correct:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

This is wrong and causes `Integration error: packages - Integration 'packages' not found`:

```yaml
packages: !include_dir_named packages
```
