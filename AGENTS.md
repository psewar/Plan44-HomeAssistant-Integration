# Contributor & agent guide

How to develop this integration. For environment setup and the check commands,
see the [README](README.md#development-quick-start); this file covers branching,
pull requests, releases, and project-specific conventions. It applies to human
contributors and coding agents alike.

## Runtime baseline

Python **3.14.3** (`.python-version`). Old-Python compatibility shims have been
removed on purpose — write for current Python and current Home Assistant.

## Branch model

- **`development`** — the active working branch. Branch off it, and open pull
  requests **into** it.
- **`main`** — release-ready code only; tags and releases are cut from `main`.
- Release flow: `development` → `main` → tag.
- Before targeting a PR, confirm which branch is actually ahead:
  `git fetch && git log --oneline -5 origin/main origin/development`.

## Pull requests

- One focused change per PR; **squash-merge** (`type: summary (#NN)`).
- Conventional-commit subjects: `fix:`, `feat:`, `chore:`, `docs:`, `refactor:`.
- All CI must pass before merge — see [`.github/workflows/ci.yml`](.github/workflows/ci.yml):

  ```bash
  ruff check .
  ruff format --check .
  pyright
  pytest tests/unit -q          # pure core/protocol tests
  pytest -c pytest.ha.ini -q    # HA component tests (Linux only; on Windows use WSL)
  ```

  `./precommit_check.sh` runs ruff + pyright + unit tests locally.

## Releasing

1. Merge `development` → `main`.
2. Bump `version` in `custom_components/plan44/manifest.json` (semver).
3. Publish a GitHub release with tag `vX.Y.Z` from `main`. The latest release is
   what HACS installs.

## Conventions & gotchas

- **Keep `plan44_core` Home-Assistant-agnostic** (no `homeassistant` imports).
  It is the source of truth for the protocol and device mappings, and the unit
  tests import it standalone.
- **Long-running background loops** (keepalives, pollers) belong on the client
  or session as a plain `asyncio.create_task`, started and cancelled together
  with the connection — **never** `hass.async_create_task(...)`. Home Assistant
  awaits tasks created that way during setup, so an endless loop there blocks
  start-up until it times out (minutes of delayed start).
- **ruff on 3.14 removes redundant parentheses**, e.g. `except (A, B):` becomes
  `except A, B:` (a valid tuple form on 3.14). Don't re-add them —
  `ruff format --check` enforces the bare form.
- **Line endings:** the repo currently mixes CRLF and LF. Preserve each file's
  existing endings and make sure a diff shows only real changes
  (`git diff --ignore-cr-at-eol --stat`).
- **Translations:** every new user-facing field needs EN **and** DE entries in
  `custom_components/plan44/strings.json`, `translations/en.json`, and
  `translations/de.json`.
- Prefer `entity_id` over `device_id` in anything that references entities.

## Tests

- `tests/unit` — pure core/protocol, no Home Assistant. Imports `plan44_core`
  as a top-level package (`tests/conftest.py` puts `custom_components/plan44` on
  the path).
- `tests/components/plan44` — HA component tests via
  `pytest-homeassistant-custom-component` (Linux/WSL).
- `tests/live` — against a real P44 bridge; see [docs/TESTING.md](docs/TESTING.md).
