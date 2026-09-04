# Configuration and setup

## Install the integration

Copy `custom_components/plan44` into your Home Assistant configuration directory and restart Home Assistant.

Then add the integration via:

- **Settings** -> **Devices & Services** -> **Add Integration**
- search for **plan44**

## Required settings

During setup you must provide:

- **Host**: hostname or IP address of your plan44 bridge
- **Port**: TCP port of the external device API, usually `8999`
- **VDC model name**: label used when the integration identifies itself to P44

Use only the hostname or IP address. Do **not** use a URL like `https://example`.

Correct:

```text
plan44.local
192.0.2.50
```

Wrong:

```text
https://plan44.local
http://192.0.2.50
```

## What this integration does

It works in **two directions**, both managed as child items (config subentries) of one `plan44` entry:

- **Export (Home Assistant → plan44)** — publish HA entities as plan44 *virtual devices*. See [Creating and managing virtual devices](VIRTUAL_DEVICES.md).
- **Import (plan44 → Home Assistant)** — bring physical devices registered on the bridge (e.g. EnOcean sensors that digitalSTROM does not expose) into HA as `sensor` / `binary_sensor` entities. See [Importing plan44 devices](DEVICE_IMPORT.md).

## Optional settings

These are available in the options flow after the integration is added:

- **Automatically republish virtual devices on startup**
- **Enable reverse control from plan44 to Home Assistant**
- **Reconnect interval**
- **Blocked integrations**
- **Blocked entity ID prefixes**

### Web API (for importing devices)

To import physical devices and read their values, the integration needs the bridge web UI login. Set these in the options flow:

- **Web API user** / **Web API password** — the bridge web UI login (HTTP Digest)
- **Device poll interval (seconds)** — how often imported device values are read (default `30`)

There is no separate URL field: the web UI is reached at `https://<host>` using the host you already entered during setup. The bridge's self-signed TLS certificate is accepted automatically. Changing any option reloads the entry so the new settings take effect immediately. Without the web credentials configured, the device picker falls back to a manual entry form.

## Multiple config entries

If you configure more than one `plan44` entry, the service calls can include `entry_id` to target a specific config entry.

Example:

```yaml
service: plan44.create_virtual_device
data:
  entry_id: YOUR_CONFIG_ENTRY_ID
  entity_id: switch.test_switch
  kind: switch
  name: Test Switch
  allow_reverse: true
```

## Recommended Home Assistant structure for virtual devices

If you plan to create multiple virtual devices, Home Assistant packages are the cleanest documented way to keep all related helper/template entities together. Home Assistant documents packages under `homeassistant: packages:` and explicitly recommends a `packages` folder loaded with `!include_dir_named packages`. 

Recommended approach:

- create `/config/packages/plan44_virtual_devices.yaml` in your Home Assistant configuration directory
- put all `plan44` helper/template entities there
- then add the resulting entities from the `plan44` integration UI

For detailed examples and sample `configuration.yaml` includes, see [Home Assistant YAML structure for virtual devices](HOME_ASSISTANT_YAML.md).


## UI-managed virtual devices

The main integration entry should only hold shared connection settings. Virtual devices should be added as child configuration items from the integration UI.

This means the UI model is:

- one parent `plan44` entry for the P44 connection
- one child entry per virtual device

This structure makes adding, editing, and removing exported entities much easier than using only service calls.
