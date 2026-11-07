---
status: accepted
date: 2026-11-07
decision-makers: kay
---

# Require Home Assistant 2026.7 so asyncssh can be 2.24 or later

## Context and Problem Statement

[ADR-0001](0001-stay-compatible-with-ha-2026-3-type-check-against-current.md)
kept the integration compatible with Home Assistant 2026.3 and, for that,
pinned `asyncssh>=2.14.0,<2.20.0` in `manifest.json`, because "2026.3 and
2026.4 ship cryptography 46, and asyncssh 2.20 needs 47". The manifest
requirement applies at runtime: Home Assistant installs asyncssh 2.19.0 into
the Python environment that all integrations share.

asyncssh 2.19.0 has three published advisories:

| Advisory | Severity | Fixed in | Reachable through this integration |
| --- | --- | --- | --- |
| [GHSA-2wxc-x7rj-hg8f](https://github.com/advisories/GHSA-2wxc-x7rj-hg8f), SCP client path traversal | high | 2.23.1 | no, it uses no SCP |
| [GHSA-qr67-gv47-xwwh](https://github.com/advisories/GHSA-qr67-gv47-xwwh), `AuthorizedKeysFile %u` | moderate | 2.23.1 | no, server side only |
| [GHSA-rw4j-r22c-9gc3](https://github.com/advisories/GHSA-rw4j-r22c-9gc3), maximum packet size 0 freezes the event loop | moderate | 2.24.0 | not with the current code: the loop needs buffered outgoing channel data, and the client only reads from its tunnel |

Checking the premise of the pin showed it was wrong in one place and right in
another:

- asyncssh 2.20.0 to 2.23.1 declare `cryptography>=39.0` and run on
  cryptography 46.0.5 and 46.0.7. Tested on Python 3.14.10 with the calls
  `bridge_client.py` makes: key import, connect, host-key capture, tunnel,
  read, refusal of a wrong pinned key.
- asyncssh 2.24.0 and 2.24.1 declare `cryptography>=48.0.1` and import
  `cryptography.hazmat.primitives.asymmetric.mlkem`, which cryptography 46
  lacks (`ImportError` when forced).
- Home Assistant pins cryptography 46.0.x up to 2026.4, 47.0.0 in 2026.5,
  48.0.0 in 2026.6 and 48.0.1 from 2026.7.

The fix for all three advisories therefore needs Home Assistant 2026.7.

The pin also conflicts with Home Assistant's own `sftp_storage` integration,
which requires `asyncssh==2.24.0` (2026.10). With both in use, each one's
requirement is unmet whenever the other one installed last.

Which asyncssh range does the integration require, and from which Home
Assistant release on?

## Decision Drivers

- No dependency with known advisories held in the environment the integration
  shares with every other integration.
- Users on older Home Assistant releases must not end up with an integration
  that fails to install or load.
- No conflict with what Home Assistant itself requires for asyncssh.

## Considered Options

1. Raise the minimum to Home Assistant 2026.7 and require `asyncssh>=2.24.0`.
2. Keep Home Assistant 2026.3 and allow up to 2.23 (`asyncssh>=2.23.1,<2.24.0`).
3. Keep the pin `<2.20`, since none of the three advisories is reachable through
   the integration's own code.

## Decision Outcome

Chosen option: 1, because it is the only one that fixes all three advisories,
and HACS keeps installations on older releases on the last version they can
run. Option 2 fixes only the two advisories that cannot be reached anyway and
keeps the conflict with `sftp_storage`. Option 3 keeps everything as it is.

- `manifest.json` and `requirements_ha_test.txt` require `asyncssh>=2.24.0`.
  The lower bound is what makes Home Assistant replace an installed 2.19.0,
  which a looser bound would accept. It is 2.24.0 rather than 2.24.1 so it is
  compatible with `sftp_storage`'s `==2.24.0`.
- No upper bound. Later asyncssh releases declare their own cryptography
  requirement, and Home Assistant's constraints decide what fits.
- `hacs.json` declares Home Assistant 2026.7.0 as the minimum (it said
  2024.12.0, below even ADR-0001's 2026.3). HACS refuses to download a release
  whose `hacs.json` minimum is above the running Home Assistant, so
  installations on 2026.3 to 2026.6 keep the version they have.
- Everything else from ADR-0001 stays, because 2026.7 still needs it:
  - `import voluptuous as vol` with the `typings/voluptuous.pyi` stub that
    points pyright at probatio, until the minimum reaches 2026.9.
  - The public `homeassistant.components.light` and `.binary_sensor` import
    paths with `# pyright: ignore[reportPrivateImportUsage]`, until the minimum
    reaches 2026.10, the first release with `binary_sensor.const` and with the
    light attributes in `light.const`.
  - CI type-checks and tests against the one release pinned in
    `requirements_ha_test.txt`.
  - Tests use `DeviceEntry.config_entry_id`, `config_subentry_id` and
    `async_get_device_by_identifier`.

### Consequences

- Good, because the shared Home Assistant environment no longer holds asyncssh
  at a version with known advisories.
- Good, because the conflict with `sftp_storage` is gone.
- Good, because `hacs.json` states the real minimum.
- Bad, because Home Assistant 2026.3 to 2026.6 no longer receive updates of the
  integration.
- Bad, because CI still checks only one release; a regression that shows only
  on 2026.7 to 2026.9 would not be caught.

### Confirmation

- `manifest.json`, `requirements_ha_test.txt` and `hacs.json` agree: asyncssh
  2.24.0 or later, Home Assistant 2026.7.0 or later. `AGENTS.md` states the
  same baseline.
- CI installs asyncssh from `requirements_ha_test.txt` and runs the component
  tests with it.
- Raising the minimum again needs a new ADR that supersedes this one and
  removes what it makes unnecessary (the stub from 2026.9, the ignores from
  2026.10).

## More Information

- Supersedes [ADR-0001](0001-stay-compatible-with-ha-2026-3-type-check-against-current.md).
- Versions are taken from the `Requires-Dist` metadata of `asyncssh` and
  `homeassistant` on PyPI, and from
  `homeassistant/components/{light,binary_sensor}/const.py` at the release
  tags.
- HACS minimum-version check: `can_download` in
  `custom_components/hacs/repositories/base.py` of
  [hacs/integration](https://github.com/hacs/integration).
