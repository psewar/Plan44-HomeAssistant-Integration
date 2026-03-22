# Release notes

This archive is the first consolidated release candidate based on live verification against a real P44 bridge.

## Verified live against real P44

- switch
- light
- sensor
- binary_sensor

## Repository cleanup already applied

Removed unnecessary empty pytest package marker files:

- `tests/live/__init__.py`
- `tests/components/plan44_integration/__init__.py`

Removed generated cache directories from the archive:

- `__pycache__/`

## Current recommended runtimes

- Python 3.14.3
- WSL2 / Linux for test execution
