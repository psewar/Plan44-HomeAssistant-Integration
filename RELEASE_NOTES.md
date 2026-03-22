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
- `tests/components/plan44/__init__.py`

Removed generated cache directories from the archive:

- `__pycache__/`

## Current recommended runtimes

- Python 3.14.3
- WSL2 / Linux for test execution

## Modernization in this build

- Switched trace timestamps back to `datetime.UTC`.
- Updated `pyrightconfig.json` to Python 3.14.
- Pinned test and tooling dependencies to their current latest stable versions.
- Marked the repository as Python-3.14-first rather than keeping older-Python compatibility shims.


## v16

- Split HA test dependencies from core/live test pins to avoid pytest resolver conflicts.
- Updated HA test dependency to `pytest-homeassistant-custom-component==0.13.319`.
- Marked `Plan44ConfigEntry` as a real type alias for stricter Pyright compatibility.
- Cleaned remaining Ruff issues in import ordering and test files.
- Replaced `asyncio.TimeoutError` with builtin `TimeoutError`.

## v19

- Removed the duplicated top-level `plan44_core` package and kept a single source of truth under `custom_components/plan44/plan44_core`.
- Updated editable packaging to expose `plan44_core` from the integration package directory.
- Added `tests/conftest.py` to make local test imports resolve consistently without duplicate code.
- Replaced PEP 695 `type` aliases with `TypeAlias` for broader formatter/tool compatibility.
