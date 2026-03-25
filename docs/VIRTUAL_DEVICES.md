# Creating and managing virtual devices

This page explains how to create Home Assistant entities that are good sources for plan44 virtual devices, and how to export them using the integration.

## Important idea

`plan44` does **not** invent its own device definitions. Instead, it takes **existing Home Assistant entities** and publishes them to plan44.

That means you first need a suitable Home Assistant entity, and then you export it.

## Recommended approach: dedicated Home Assistant package file

Do **not** add helper or template YAML files to the `plan44` integration repository.

Instead, create a dedicated YAML file in your **Home Assistant configuration directory** and keep all helper entities and template entities for `plan44` there. Home Assistant officially recommends packages for bundling related configuration, and documents `homeassistant: packages: !include_dir_named packages` as the convenient approach for this. The package docs also state that this method loads YAML files in the packages folder and its subfolders. citeturn324374view0

Recommended file name:

```text
/config/packages/plan44_virtual_devices.yaml
```

If you prefer a grouped structure, this is also fine:

```text
/config/packages/plan44/virtual_devices.yaml
```

See [Home Assistant YAML structure for virtual devices](HOME_ASSISTANT_YAML.md) for concrete include examples and directory layouts.

## What to use as source entities

### `switch`

The service expects a real `switch.*` entity for `kind: switch`.

A common mistake is to assume Home Assistant has a native helper named `switch`. For simple virtual toggles, the usual helper is actually **`input_boolean`**.

Because `plan44` validates entity domains, the clean pattern is:

- create an `input_boolean`
- expose it as a **template switch**
- export the resulting `switch.*` entity

Example:

```yaml
input_boolean:
  plan44_test_switch_state:
    name: Plan44 Test Switch State

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
```

This gives you a proper `switch.plan44_test_switch` entity that can be exported.

### `light`

Use a real `light.*` entity. This can come from:

- an existing integration
- MQTT light
- a template-based light setup
- another local test setup

For `light`, the integration expects an actual `light` domain entity.

### `sensor`

For numeric values, a clean pattern is:

- create an `input_number` helper
- expose it as a template sensor
- add the resulting `sensor.*` entity in the `plan44` UI

Example:

```yaml
input_number:
  plan44_test_temperature_raw:
    name: Plan44 Test Temperature Raw
    min: 0
    max: 50
    step: 0.1
    mode: box

template:
  - sensor:
      - name: "Plan44 Test Temperature"
        unique_id: plan44_test_temperature
        unit_of_measurement: "°C"
        device_class: temperature
        state_class: measurement
        state: "{{ states('input_number.plan44_test_temperature_raw') | float(0) }}"
```

In the UI, select the resulting entity:

- `sensor.plan44_test_temperature`

Do not select the raw helper `input_number.plan44_test_temperature_raw`, because `plan44` only accepts numeric entities from the `sensor` domain for the virtual device type `sensor`.

### `binary_sensor`

For contact-like states, use an `input_boolean` and expose it as a template binary sensor.

Example:

```yaml
input_boolean:
  plan44_test_contact_state:
    name: Plan44 Test Contact State

template:
  - binary_sensor:
      - name: "Plan44 Test Contact"
        unique_id: plan44_test_contact
        state: "{{ is_state('input_boolean.plan44_test_contact_state', 'on') }}"
```

## Adding the virtual device to `plan44`

Once the Home Assistant entity exists, the preferred approach is to add it from the `plan44` integration UI:

1. Open **Settings -> Devices & Services**
2. Open **plan44**
3. Choose **Add virtual device**
4. Select the source entity from the entity selector
5. Choose the matching kind
6. Save

The legacy services below still work, but they are now the secondary path.

## Legacy service examples

### Switch example

```yaml
service: plan44.create_virtual_device
data:
  entity_id: switch.plan44_test_switch
  kind: switch
  name: Plan44 Test Switch
  allow_reverse: true
```

### Light example

```yaml
service: plan44.create_virtual_device
data:
  entity_id: light.my_virtual_light
  kind: light
  name: My Virtual Light
  allow_reverse: true
```

### Sensor example

```yaml
service: plan44.create_virtual_device
data:
  entity_id: sensor.plan44_test_temperature
  kind: sensor
  name: Plan44 Test Temperature
```

### Binary sensor example

```yaml
service: plan44.create_virtual_device
data:
  entity_id: binary_sensor.plan44_test_contact
  kind: binary_sensor
  name: Plan44 Test Contact
```

## Other services

### Remove a virtual device

```yaml
service: plan44.remove_virtual_device
data:
  entity_id: switch.plan44_test_switch
```

### Republish all configured virtual devices

```yaml
service: plan44.republish_virtual_devices
```

### Push current state again

```yaml
service: plan44.push_entity_state
data:
  entity_id: sensor.plan44_test_temperature
```

## Recommended naming conventions

To keep things readable, use a consistent naming scheme for helper entities, for example:

- `input_boolean.plan44_*`
- `input_number.plan44_*`
- `switch.plan44_*`
- `sensor.plan44_*`
- `binary_sensor.plan44_*`

This makes it obvious which entities are meant to be exported.

## Notes on reverse control

Reverse control from plan44 back to Home Assistant currently matters mainly for:

- `switch`
- `light`

For `sensor` and `binary_sensor`, the main use case is sending Home Assistant state **to** plan44.


## Recommended management model

- keep source helpers/entities in Home Assistant YAML or helpers
- keep them grouped in a dedicated `plan44` package file
- manage exported virtual devices primarily from the `plan44` integration UI
- keep the legacy services for automation or migration use cases

As of the current UI design, virtual devices should primarily be managed directly from the Home Assistant integration UI using **config subentries**:

1. Add the main `plan44` integration once for the shared connection settings.
2. Open the `plan44` integration entry.
3. Use **Add virtual device** to create one child configuration item per exported entity.
4. Edit or remove those child items directly from the UI later.

The existing service actions remain available as a compatibility layer, but the preferred long-term workflow is the UI-driven subentry model.

## Suggested Home Assistant package file

For helper-based virtual devices, it is still a good idea to keep the helper entities themselves in a dedicated Home Assistant package file, for example:

```text
packages/plan44_virtual_devices.yaml
```

This file contains the source entities (for example `input_boolean`, template `switch`, template `sensor`, template `binary_sensor`).
The `plan44` integration UI then only needs to reference those already existing entities.
