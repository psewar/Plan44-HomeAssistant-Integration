# Importing plan44 devices into Home Assistant

Besides exporting Home Assistant entities to plan44 (see
[Creating and managing virtual devices](VIRTUAL_DEVICES.md)), the integration can
go the other way: bring **physical devices registered on the plan44 bridge** into
Home Assistant as `sensor` and `binary_sensor` entities.

This is useful for devices that digitalSTROM does not expose to Home Assistant —
for example the acceleration/motion channels of an EnOcean multisensor, or a
smoke/contact input.

## How values flow

### Light output devices (Hue, dimmable actuators)

Imported light entities receive **push updates** via the plan44 TCP connection
(port 8999).  After connecting, the integration subscribes to `channelStates`
events from the bridge.  When a light changes state — whether from HA, the Hue
app, a physical dimmer, or a plan44 scene — the bridge sends a `channelStates`
notification and HA reflects the new state immediately.

Polling over the web vdc JSON API continues at the configured interval as a
fallback.  If the bridge firmware does not support the subscription (a one-time
`WARNING` is logged), the integration silently falls back to poll-only.

### Sensor / binary_sensor devices (EnOcean, etc.)

After connecting, the integration also subscribes to `sensorStates` and
`binaryInputStates` push events.  When the plan44 bridge forwards a sensor
value change or binary input transition, the entity state is updated
immediately — no HTTP round-trip.

```json
{"message": "subscribe", "events": ["channelStates", "sensorStates", "binaryInputStates"]}
```

A typical push notification for a sensor device looks like:

```json
{"message": "sensorStates", "dSUID": "...", "sensorStates": {"temperature": {"value": 21.5}},
 "binaryInputStates": {"low_battery": {"value": false}}}
```

Polling over the web vdc JSON API continues at the configured interval as
fallback — useful for devices with slow natural update intervals (e.g. an
EnOcean temperature sensor that reports every 5 min) or if the bridge
firmware does not emit push events for a particular device type.

## 1. Configure the web API (once)

Open **Settings → Devices & Services → plan44 → Configure** and enter the bridge
web UI **user + password** (and optionally the poll interval). The URL is derived
from the host you already configured (`https://<host>`). See
[Configuration](CONFIGURATION.md#web-api-for-importing-devices) for details.

## 2. Import a device

1. Open the `plan44` integration and choose **+ Import P44 device**.
2. Pick a device from the dropdown. The list is read live from the bridge and
   shows each device's name and model.
3. Save. The integration reads the device's channel descriptions and creates the
   matching entities automatically — units and device classes are derived from
   the bridge's own metadata (e.g. `celsius → °C / temperature`,
   `kilowatthour → kWh / energy`, a low-battery input → `battery`).

All channels of one device are grouped under a single Home Assistant device.

### New devices added later

The device list is fetched fresh every time you open the import dialog, so
devices added to the bridge after setup appear automatically — no need to
reinstall or restart the integration.

## Manual import (no web API)

If the web API is not configured, the import dialog falls back to a manual form:

- **Plan44 device tag** — the bridge device id (e.g. `enoceanaddress:00123456`)
- **Device profile** — a built-in template describing the channels, or
  **Single sensor (manual)** for a one-off channel

Manual entries use the push path (TCP external device API, port 8999). Note that
physical devices generally do not push there, so the web-API picker above is the
reliable way to see live values. Built-in profiles include common EnOcean types
(D2-14-40/41, D2-14-30, A5-20-01/06, A5-10-12, A5-07-01, D5-00-01) plus smart-plug
metering and a weather profile. Profiles live in
`custom_components/plan44/device_templates.py` and are easy to extend.

## Inspecting the bridge from the command line

`devtools/dump_p44_devices.py` lists every device on the bridge with its channels
and current values. Credentials are read from the environment, never the command
line:

```bash
# devtools/.env.p44 (gitignored): P44_URL, P44_USER, P44_PASSWORD
set -a; . devtools/.env.p44; set +a
python devtools/dump_p44_devices.py --url "$P44_URL"
python devtools/dump_p44_devices.py --url "$P44_URL" --out devtools/devices.json
```

This is handy for finding a device's tag/model or verifying that the web API is
reachable.
