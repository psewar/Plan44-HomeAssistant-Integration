# Testing and live verification

This repository uses three test layers.

## 1. Unit tests

These test the protocol, mapping, templates and web-API parsing without needing
Home Assistant or a real P44 bridge.

Run:

```bash
pytest tests/unit -q
```

## 2. Home Assistant component tests

These exercise the config/options/subentry flows and the entity platforms using
the `pytest-homeassistant-custom-component` harness.

```bash
pytest -c pytest.ha.ini -q
```

These require Linux (see the Windows note below) — run them under WSL on Windows.
CI runs both the unit and component layers.

## 3. Live tests against a real P44 bridge

These tests verify that the generated messages are accepted by a real P44 bridge.

Currently live-verified:

- `switch`
- `light`
- `sensor`
- `binary_sensor`

## Environment file

Create:

```text
devtools/.env.live
```

Example:

```env
P44_TEST_ENABLED=1
P44_TEST_HOST=192.0.2.50
P44_TEST_PORT=8999
P44_TEST_MODEL="plan44_core live tests"
P44_TRACE_PATH=artifacts/p44_live_trace.jsonl
```

Important:

- `P44_TEST_HOST` must be a hostname or IP address only
- do not use `https://...`

## Run live tests

Run all live tests:

```bash
pytest -c pytest.live.ini tests/live -vv -s
```

Run a single device type:

```bash
pytest -c pytest.live.ini tests/live -k switch -vv -s
pytest -c pytest.live.ini tests/live -k light -vv -s
pytest -c pytest.live.ini tests/live -k sensor -vv -s
pytest -c pytest.live.ini tests/live -k binary_sensor -vv -s
```

## Trace output

The live test harness can write a JSONL trace file, for example:

```text
artifacts/p44_live_trace.jsonl
```

Inspect it with:

```bash
cat artifacts/p44_live_trace.jsonl
```

This is the most useful artifact when validating a new device type or debugging a rejected message.

## Inspecting bridge devices (web API)

`devtools/dump_p44_devices.py` lists every device on the bridge with its channels
and current values via the web vdc JSON API. Credentials come from a local
gitignored file (`devtools/.env.p44`: `P44_URL`, `P44_USER`, `P44_PASSWORD`) and
are never passed on the command line:

```bash
set -a; . devtools/.env.p44; set +a
python devtools/dump_p44_devices.py --url "$P44_URL"
```

See [Importing plan44 devices](DEVICE_IMPORT.md) for how this maps to imported
entities.

## Windows note

`pytest-homeassistant-custom-component` imports parts of Home Assistant that rely on POSIX modules such as `fcntl`.

Because of that, Home Assistant related tests should be run in:

- WSL2
- Docker
- Linux

The live/core tests were separated to keep protocol development simpler.


## Local repository checks

Use the shell-specific helper at the repository root:

- WSL / Linux / bash: `./precommit_check.sh`
- PowerShell: `./precommit_check.ps1`
