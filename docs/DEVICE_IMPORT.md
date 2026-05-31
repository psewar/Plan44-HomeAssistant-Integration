# Importing plan44 devices into Home Assistant

Besides exporting Home Assistant entities to plan44 (see
[Creating and managing virtual devices](VIRTUAL_DEVICES.md)), the integration can
go the other way: bring **physical devices registered on the plan44 bridge** into
Home Assistant as `sensor` and `binary_sensor` entities.

This is useful for devices that digitalSTROM does not expose to Home Assistant —
for example the acceleration/motion channels of an EnOcean multisensor, or a
smoke/contact input.

## How values flow

Physical plan44 devices do **not** push to the external device API, so the
integration reads their values from the bridge's **web vdc JSON API** by polling.
Each imported device becomes one Home Assistant *device*, with one entity per
sensor/input channel.

Because this is polling, fast-changing inputs such as motion or contact are
updated at the configured poll interval (default 30 s), not instantly.

## 1. Configure the web API (once)

Open **Settings → Devices & Services → plan44 → Configure** and fill in the
web API fields (URL + web UI login + poll interval). See
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
