# Testing and live verification

This repository uses two different test layers.

## 1. Unit tests

These test the protocol and mapping logic without needing Home Assistant or a real P44 bridge.

Run:

```bash
pytest tests/unit -q
```

## 2. Live tests against a real P44 bridge

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
P44_TEST_HOST=utgard.gothrist.ch
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

## Windows note

`pytest-homeassistant-custom-component` imports parts of Home Assistant that rely on POSIX modules such as `fcntl`.

Because of that, Home Assistant related tests should be run in:

- WSL2
- Docker
- Linux

The live/core tests were separated to keep protocol development simpler.
