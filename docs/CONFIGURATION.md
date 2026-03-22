# Configuration and setup

## Install the integration

Copy `custom_components/plan44_integration` into your Home Assistant configuration directory and restart Home Assistant.

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
utgard.gothrist.ch
192.168.1.50
```

Wrong:

```text
https://utgard.gothrist.ch
http://192.168.1.50
```

## Optional settings

The integration also supports:

- **Automatically republish virtual devices on startup**
- **Enable reverse control from plan44 to Home Assistant**
- **Reconnect interval**
- **Blocked integrations**
- **Blocked entity ID prefixes**

These are available in the options flow after the integration is added.

## Multiple config entries

If you configure more than one `plan44` entry, the service calls can include `entry_id` to target a specific config entry.

Example:

```yaml
service: plan44_integration.create_virtual_device
data:
  entry_id: YOUR_CONFIG_ENTRY_ID
  entity_id: switch.test_switch
  kind: switch
  name: Test Switch
  allow_reverse: true
```

## Recommended Home Assistant structure for test and virtual devices

If you plan to create multiple virtual devices, it is a good idea to keep their helper entities in a dedicated Home Assistant config file or package.

Recommended approaches:

- a dedicated package file such as `packages/plan44_virtual_devices.yaml`
- a local file such as `packages/local/plan44_virtual_devices.yaml`
- UI-created helpers with a consistent naming convention like `input_boolean.plan44_*`

A dedicated file keeps the setup understandable and makes it easier to see which Home Assistant entities are intended for export to plan44.

For concrete examples, see [Creating and managing virtual devices](VIRTUAL_DEVICES.md).


## UI-managed virtual devices

The main integration entry should only hold shared connection settings. Virtual devices should be added as child configuration items from the integration UI.

This means the UI model is:

- one parent `plan44` entry for the P44 connection
- one child entry per virtual device

This structure makes adding, editing, and removing exported entities much easier than using only service calls.
