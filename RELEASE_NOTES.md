# Release notes

## 0.5.6 — 2026-06-01

- **Fix: editing an imported (picker) device no longer shows a stray device-tag
  field.** Devices imported from the live bridge are identified by their dSUID
  and their channels come from the bridge, so the *Edit* dialog now offers only
  the display name. Previously it reused the manual-import form — showing an
  empty, *required* "Plan44 device tag" plus a profile dropdown that didn't
  apply, and it could inject an unused `p44_tag`/`template` into the device's
  data on save. Manual (tag + profile) devices are unaffected and keep the full
  form.

## 0.5.5 — 2026-06-01

- **Automatic circular-reference guard.** An entity that this integration itself
  imported from the bridge (a `p44_device`) can no longer be exported back to
  plan44 as a virtual device — that would be a direct loop (P44 → HA → P44).
  Such entities are detected via their registry platform (`plan44`) and rejected
  with a clear "would create a loop" message, both in the *Add virtual device*
  UI and on the export service path. This is always on and needs no
  configuration.
- **Blocked integrations is now a multi-select** of the integrations actually
  installed in your Home Assistant, instead of a free-text, comma-separated
  field — fewer typos, and you can still type a custom value for an integration
  that isn't installed yet. Existing comma-separated settings are migrated
  transparently. (Blocked `entity_id` prefixes stay a text field, since prefixes
  are patterns rather than concrete entities.)

> Note: cross-bridge loops (e.g. digitalSTROM → HA → plan44 → digitalSTROM)
> can't be proven automatically because the integration doesn't know your
> downstream topology — the (now friendlier) blocklist remains the tool for
> those.

## 0.5.4 — 2026-05-31

- **Simpler "Add virtual device" flow.** You no longer choose a device type first
  and then an entity — just pick the entity (filtered to switch / light / sensor /
  binary_sensor) and the type is derived from its domain automatically. One step
  instead of two, and the "type doesn't match the entity" error is gone.
- Moved the virtual-device validation messages under the subentry's own
  translation block (where Home Assistant looks them up) and dropped the now-dead
  `kind_mismatch` string.

## 0.5.3 — 2026-05-31

- **Fix "Translation error: UNCLOSED_TAG" when opening the plan44 options.** The
  options description contained `https://<host>`, and Home Assistant's translation
  renderer treats `<host>` as an unclosed rich-text tag. Reworded without angle
  brackets.
- Added a unit test that guards every translation string against tag-like
  `<...>` markup, so this class of bug can't reach the UI again.

## 0.5.2 — 2026-05-31

- **Removed the "Web API URL" option entirely.** The web UI is always reached at
  `https://<host>` using the host entered during setup, so importing devices only
  needs a web user + password — the redundant URL field is gone.
- Internal clean-up that came with it: dropped the now-unused `web_url`
  config key and a dead `Plan44WebApi.async_validate` method.

## 0.5.1 — 2026-05-31

- **Web API URL is now derived from the connection host** (`https://<host>`), so
  importing devices only needs a web user + password in the options — no need to
  re-enter the URL you already gave during setup. The URL field stays as an
  optional override.
- The device picker no longer **silently** falls back to the manual form when the
  web API is configured but unreachable / returns no devices — it now shows a
  clear error explaining why.

## 0.5.0 — 2026-05-31

Device import + quality work, all verified in CI (Ruff, Pyright, unit + Home
Assistant component tests) and partly against a live P44-DSB-E2 bridge.

- **Import physical plan44 devices into Home Assistant** as `sensor` /
  `binary_sensor` entities (new `p44_device` config subentry, new platforms).
- **Live device picker:** when the bridge web API is configured, pick a device
  from a dropdown read live from the bridge; channels (units, device classes)
  are derived automatically and grouped as one HA device.
- **Web vdc JSON API client** + polling coordinator (web user / password / poll
  interval in the options flow). Self-signed TLS accepted.
- **Built-in EnOcean device profiles** (D2-14-40/41, D2-14-30, A5-20-01/06,
  A5-10-12, A5-07-01, D5-00-01) plus smart-plug metering and weather, with a
  manual single-channel fallback.
- **UI fix:** the subentry “+” buttons are now labelled (“Add virtual device”,
  “Import P44 device”) via `initiate_flow` / `entry_type` translations.
- `devtools/dump_p44_devices.py` to enumerate bridge devices (credentials from a
  gitignored `.env.p44`, never the command line).
- Robustness/clean-up: non-numeric sensor fallback, unknown-unit warning,
  `state_mapping` extracted from the coordinator, dead code removed, expanded
  test suite, CI now runs the Home Assistant component tests.

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

- Added two-step virtual-device UI flow: choose type first, then select a source entity filtered to that type.
- Clarified README/Home Assistant YAML docs and improved the numeric sensor example.
