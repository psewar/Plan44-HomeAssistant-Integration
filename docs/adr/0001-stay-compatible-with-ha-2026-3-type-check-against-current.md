---
status: proposed
date: 2026-11-04
decision-makers: kay
---

# Stay compatible with Home Assistant 2026.3, type-check against the current release

## Context and Problem Statement

The integration runs on Python 3.14 and uses syntax that needs it
(`except A, B:`), so the oldest Home Assistant it can load on is 2026.3, the
first release on Python 3.14. The test environment pins one Home Assistant
release through `pytest-homeassistant-custom-component`. Raising it from
2026.3.3 to 2026.10.4 surfaced three kinds of problems, although the
integration already ran on 2026.10.4 unchanged:

- Home Assistant 2026.9 replaced voluptuous with probatio and types schema
  parameters (`async_show_form(data_schema=...)`, `async_register(schema=...)`)
  with probatio classes. At runtime HA aliases `voluptuous` to probatio, but
  pyright sees the separately installed voluptuous and reports every
  `vol.Schema` as the wrong type.
- The `light` and `binary_sensor` packages now re-export `ATTR_BRIGHTNESS`,
  `BinarySensorDeviceClass` and similar names from `.const` without
  `__all__`, which pyright strict reports as private imports.
- Tests read deprecated `DeviceEntry` members and the deprecated
  `device_registry.async_get_device`; HA now fails such calls in tests.

How do we test and type-check against the current Home Assistant without
dropping the older releases the integration still supports?

## Decision Drivers

- Users on Home Assistant 2026.3 to 2026.8 keep a working integration.
- CI checks the code against the release most users run.
- No silent switches: every exception to pyright strict is visible at the line
  it covers.

## Considered Options

1. Keep the imports, type-check against the current release, and mark the
   gaps explicitly (a `voluptuous` stub that points at probatio, per-line
   pyright ignores for the root re-exports).
2. Import `probatio` and the `.const` modules directly, and raise the minimum
   to Home Assistant 2026.9.
3. Keep the test environment at 2026.3.3.

## Decision Outcome

Chosen option: 1, because it is the only one that keeps 2026.3 to 2026.8
working and still checks the code against 2026.10.

- `import voluptuous as vol` stays, as Home Assistant recommends for custom
  integrations. `typings/voluptuous.pyi` re-exports probatio for pyright only,
  which matches what HA does at runtime.
- Imports from `homeassistant.components.light` and `.binary_sensor` stay on
  the public package path that Home Assistant itself uses. Each name pyright
  reports as private carries `# pyright: ignore[reportPrivateImportUsage]` and
  a comment with the reason. The `.const` modules are not an option, because
  2026.3 defines these names in the package itself and has no
  `binary_sensor.const`.
- Tests use `DeviceEntry.config_entry_id`, `config_subentry_id` and
  `async_get_device_by_identifier`, which 2026.10 provides.
- The `asyncssh<2.20` pin stays: 2026.3 and 2026.4 ship cryptography 46, and
  asyncssh 2.20 needs 47.

### Consequences

- Good, because nothing changes at runtime and the supported range stays
  2026.3 and later.
- Good, because CI type-checks against the probatio types HA actually uses.
- Bad, because CI checks only one release (2026.10.4); a regression that
  shows only on 2026.3 to 2026.8 would not be caught.
- Bad, because the stub and the ignores must be removed once the minimum
  reaches a release where they are no longer needed (probatio import from
  2026.9; `.const` imports once every supported release has them).

### Confirmation

`pyright` in CI runs strict against the pinned Home Assistant release; the
ignores are greppable (`reportPrivateImportUsage`). Raising the minimum Home
Assistant version needs a new ADR that supersedes this one and removes what
it makes unnecessary.

## More Information

- Home Assistant: [Probatio is our validation engine](https://contributors.home-assistant.io/blog/2026/09/30/probatio-validation-engine/)
  (2026-09-30) and
  [DeviceEntry.config_entries deprecation is now enforced](https://contributors.home-assistant.io/blog/2026/09/15/device-entry-config-entries-deprecation/)
  (2026-09-15).
- `hacs.json` still declares Home Assistant 2024.12.0 as the minimum, below the
  effective 2026.3. Correcting it is a separate change.
