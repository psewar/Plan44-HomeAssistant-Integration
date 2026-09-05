# Release notes

## 0.9.4 — 2026-09-06

More of what the bridge already knows about an imported light.

- **A lamp the bridge reports as inactive is now unavailable.** 0.9.3 did this
  for sensors but missed lights: a Hue lamp cut from power at the wall switch
  keeps its node *and its last channel values* on the bridge, so the entity
  went on reporting a stale "on" indefinitely. The light poll now asks for the
  same `active` flag the sensors use.
- **`transition:` works.** The bridge advertises a variable ramp for these
  devices and the hue vdc forwards the time to the lamp, but the call the
  integration used (`setProperty` on `channelStates`) has no way to carry it,
  so every fade in a script or scene was silently dropped and the light
  snapped. Fades now go out as the `setOutputChannelValue` notification, which
  does carry `transitionTime`; without a `transition:` nothing is imposed on
  the device and the single-request path is kept.
- **New "Identify" button** per imported light — makes the lamp blink, which
  is the quickest way to tell several identical ones apart.
- **The device page links to the bridge**, so scenes, groups and dim curves
  are one click away.
- **Devices show their real manufacturer** where the bridge names one (a Hue
  lamp now says Signify rather than plan44). Devices imported before this
  release keep the old attribution until they are re-imported.

## 0.9.3 — 2026-09-04

- **A device that stops reporting is now visible.** The bridge keeps a silent
  device in its device list but nulls every value, so the entities used to sit
  on "unknown" indefinitely while still reporting themselves as *available* —
  a flat battery or an out-of-range radio sensor looked exactly like a device
  that had simply not sent its first value yet. The poll now also asks the
  bridge for its own `active` flag and marks the entities **unavailable** when
  the bridge says the device has gone silent, so Home Assistant's usual
  unavailability tooling (dashboards, `unavailable` triggers) catches it.
  A real-time push counts as the device reporting and clears the flag
  immediately, so a device that wakes up does not stay unavailable until the
  next poll. A bridge that does not report `active` at all is treated as
  before (available).

## 0.9.2 — 2026-08-12

- **Transient bridge blips no longer abort automations.** The vdcd bridge
  periodically closes the connection from its side; a vdc request landing in
  that window returned a reset socket or an empty body and failed hard, taking
  down whatever triggered it (for example a sunrise wake-up-light automation
  dying mid-run). Such requests are now retried up to three times with a short
  growing pause, while certificate, auth and over-sized-response errors still
  fail immediately.

## 0.9.1 — 2026-08-06

Follow-up to the 0.9.0 review — completes two fixes that were incomplete and
closes the remaining verified findings.

- **The pinned SSH host key could never be cleared.** 0.9.0 pins the bridge
  host key and refuses a different one, but nothing could forget it: the key
  lives in the config entry's *data* while the options flow writes *options*,
  so the "turn real-time mode off and on again" advice in the error message did
  nothing. After a genuine bridge reinstall the tunnel was stuck until the
  entry was deleted. New option **"Forget the pinned SSH host key"** does it
  properly, and the error message now points at it.
- **A failed setup no longer leaks the connection.** Anything raising between
  the initial connect and the end of setup left the socket, the reader and
  keepalive tasks and the state listener running — and each retry added
  another, each with 0.9.0's never-give-up reconnect loop.
- **State forwarding can no longer resurrect a torn-down connection.** A
  fire-and-forget forward task that was in flight during a reload could
  re-open a socket that nothing owned.
- **A failing republish no longer drives the reconnect loop** — the link is up
  at that point, so it was spinning (and inflating the reconnect counter)
  while everything worked.
- **Non-finite values from the bridge** (`NaN`/`Infinity`, which JSON allows)
  are now dropped instead of raising inside a coordinator update, where the
  traceback cost every entity queued behind it.
- The discovery notification no longer re-fires for an already-reported
  channel; connection errors in the config flow are logged instead of silently
  becoming "cannot connect"; the device picker no longer ignores the
  "verify SSL" setting; diagnostics and system health now show the real-time
  link state and whether the TLS certificate is actually pinned.
- Internal: removed a dead coordinator hook, declared two attributes in
  `__init__` instead of creating them on the fly.

## 0.9.0 — 2026-08-06

Hardening release from a full security / performance / clean-code review.

### Security

- **The SSH private key was written to the diagnostics file in clear text.**
  `TO_REDACT` was never extended when the real-time SSH option was added in
  0.8.0, so downloading diagnostics exposed the key that grants access to the
  bridge. It (and the SSH host/port/user, the pinned host key and the TLS
  certificate) are now redacted. **If you downloaded or shared a diagnostics
  file from 0.8.0–0.8.2, rotate that SSH key.** A guard test now fails if any
  future credential-ish option is added without redacting it.
- **The SSH tunnel now pins the bridge host key (trust-on-first-use).**
  Previously it accepted any host key, so anything able to intercept the SSH
  path could impersonate the bridge. The key is captured on first connect and
  stored; later connections accept only that key and otherwise refuse with a
  clear message. To re-pin after a genuine bridge reinstall, turn real-time
  mode off and on again in the options.
- **Malformed data from the bridge can no longer tear down the connection.**
  A non-numeric channel `index` raised inside the TCP reader loop, killing the
  session (and every push with it) on a single bad message; it is now rejected
  like a bad value. The discovery cache keyed by bridge-supplied tags is now
  bounded, so an unexpected flood of tags cannot grow memory or spam
  notifications without limit.

### Performance / correctness

- **Real-time pushes no longer starve the REST poll.** Pushes went through
  `async_set_updated_data()`, which reschedules the poll timer and marks the
  update successful — a steady push stream stopped polling entirely and a
  broken web API kept reporting healthy. Pushes now update the data and notify
  listeners without touching the poll timer or the success flag, and a push
  carrying an unchanged value no longer wakes every entity.
- **The bridge connection no longer gives up permanently.** After 10 failed
  reconnects the integration stayed dead until Home Assistant was restarted;
  it now keeps retrying with backoff (and stops spamming the log after the
  first attempts).
- **A tunnel that opens and immediately drops no longer reconnect-storms** —
  the backoff only resets after a session that actually stayed up.
- `async_unload_entry` now reports the real platform-unload result instead of
  always returning `True`, and stopping the bridge client no longer swallows
  cancellation.
- The real-time link state is now logged and broadcast, so a permanently dead
  tunnel is visible instead of silently degrading to poll-only.

## 0.8.2 — 2026-08-06

- **Keep the real-time bridge connection alive across a firewall / port-forward.**
  The bridge-API stream is mostly idle between value changes, and an idle SSH
  session through a NAT/proxy gets dropped (~30 s) — the client would connect,
  lose the connection, and slowly back off. Added an SSH keepalive (every 15 s)
  so the tunnel stays up, and the reconnect backoff now resets after any real
  session so a drop retries in ~5 s instead of up to 120 s.

## 0.8.1 — 2026-08-06

- **Real-time bridge API: separate optional "SSH host" field.** The SSH tunnel
  defaulted to the connection host, but on some setups that hostname's port 22
  routes elsewhere (firewall / reverse tunnel) while the web/TCP API still works
  — causing `Permission denied`. You can now set a distinct SSH host (e.g. the
  bridge's LAN IP); leave it empty to keep using the connection host.

## 0.8.0 — 2026-08-06

### Optional real-time updates for imported devices via the bridge API (SSH)

Imported (dSUID) devices can now update **in real time** instead of only on the
poll interval, by reading the bridge's *bridge API* (the same JSON API p44mbrd /
Matter uses) over an SSH tunnel. Unlike Matter, this carries the **raw** device
channels — including ones Matter cannot represent, e.g. acceleration X/Y/Z.

Enable it under the integration options — *"Real-time updates via bridge API
(SSH)"* — and supply an SSH user plus a dedicated, forward-only private key for
the bridge. The client opens an SSH `direct-tcpip` channel to the bridge API on
`127.0.0.1:4444` and feeds every `pushNotification` into the existing imported
entities; the REST poll stays active as a fallback / initial backfill. This is
fully opt-in — nothing changes unless you enable it.

Notes:
- Only devices flagged for bridging on the bridge (its *"Bridge to Matter"*
  per-device option) are pushed.
- The bridge API stays localhost-only; the SSH key only needs port-forwarding
  (install it with `no-pty` + a forced command), so it can't open a shell.
- Adds `asyncssh` as a dependency (pinned `<2.20` for compatibility with Home
  Assistant's bundled cryptography).

## 0.7.8 — 2026-07-15

### Removed the non-functional imported-device push path

Live testing against the bridge showed that the external device API (port 8999)
does **not** deliver push events for imported (foreign) devices: the `subscribe`
message is rejected (`no device tagged '' found`) and no `channelStates` /
`sensorStates` / `binaryInputStates` notifications are ever sent. Those device
events are routed by the bridge to the digitalSTROM vdSM, not to the external
device API.

The subscribe/apply code path was therefore dead. This release removes it
entirely — `_async_subscribe_push()`, the dSUID push routing in
`async_handle_plan44_message()`, the `async_apply_push_*` coordinator methods,
the `parse_push_sensor_states` helper, and the `push_enabled` option toggle —
together with the tests that covered it. The documentation is corrected
accordingly: **imported devices are polled** from the web vdc JSON API at the
configured interval.

This corrects the 0.7.5 note below, which claimed sensor/binary\_sensor entities
update via push. They do not; they are polled.

Export (HA → plan44) and control-back for exported / manual tag-based devices are
unaffected and continue to use the external device API as before, so
`iot_class: local_push` still reflects that push-based control path.

---

## 0.7.5 — 2026-07-11

### Push updates extended to sensor and binary\_sensor entities

Imported sensor and binary\_sensor devices (EnOcean, etc.) now also update via
push instead of polling-only.  The integration now subscribes to all three
plan44 push event types after connecting:

```json
{"message": "subscribe", "events": ["channelStates", "sensorStates", "binaryInputStates"]}
```

When the plan44 bridge sends a `sensorStates` or `binaryInputStates`
notification (e.g. temperature changed, battery went low), the entity state is
updated immediately — no HTTP round-trip.  Polling continues at the configured
interval as a reliable fallback and handles devices that do not produce push
events (e.g. slow EnOcean update-interval sensors).

Previously, sensor/binary\_sensor updates relied on polling alone (default 30 s),
so a door contact or motion event could be missed for up to 30 s.  With push,
binary inputs that change state now update instantly.

**Integration class:** `iot_class: local_push` now correctly reflects actual
behaviour for all three imported device types.

---

## 0.7.4 — 2026-07-11

### Push updates for imported light entities (local\_push)

Light output devices (e.g. Philips Hue lights imported via the plan44 web API)
now update instantly in Home Assistant whenever their state changes — regardless
of the source (Hue app, physical dimmer, plan44 scene, or HA itself).

After connecting over TCP, the integration subscribes to
`channelStates` push events from the plan44 bridge:

```json
{"message": "subscribe", "events": ["channelStates"]}
```

When the bridge sends a `channelStates` notification for a known imported light,
the entity state is updated immediately without an HTTP round-trip.  Polling over
the web vdc JSON API continues at the configured interval as a reliable fallback
(in case the bridge firmware does not support the subscription, or a push message
is lost).  If the subscription is not supported, a `WARNING` is logged once and
the integration falls back to poll-only automatically.

**Integration class:** `iot_class: local_push` (was already declared; now
correctly reflects actual behaviour for light entities).

**Also in 0.7.x** (not previously documented):

- **0.7.0** — New `light` platform: import Hue and other output devices from the
  plan44 bridge as `light` entities.  Brightness, colour temperature, HS colour,
  and CIE x/y colour (native Hue colour space) are all supported.  Devices are
  imported via **+ Import P44 device** in the same way as sensors; channel
  capabilities (colour temp range, HS, XY) are detected automatically from the
  bridge's `channelDescriptions`.
- **0.7.2** — XY colour mode: the native CIE x/y channels are preferred over HS
  when both are present (round-trip-free, more accurate).  HS input from HA is
  converted to XY before sending to the bridge.
- **0.7.3** — Fix: imported Hue lights showed "unavailable" immediately after
  setup.  Root cause: the node-traversal helper used when polling channel states
  required `channelDescriptions` to be present, but the state-only query returns
  only `channelStates` — so every polling response matched zero nodes.  Fixed by
  accepting nodes that carry either `channelDescriptions` **or** `channelStates`.

## 0.6.0 — 2026-06-09

Security hardening + clean-up from a full review of the integration.

- **Diagnostics no longer leak the web API password.** The downloadable
  diagnostics now redact `web_user` and `web_password` (previously only the
  host/port/model were redacted). Anyone who already shared a diagnostics file
  should rotate the bridge web password.
- **The bridge TLS certificate is now pinned (trust-on-first-use)** instead of
  disabling verification entirely. On first contact the self-signed certificate
  is fetched and stored; later web-API calls verify the peer against exactly
  that certificate, which protects against man-in-the-middle on the LAN. If the
  bridge certificate later changes, the call fails with a clear message — remove
  and re-add the web credentials in the options to re-pin. (If the certificate
  can't be fetched, it falls back to the previous unverified behaviour so the
  integration keeps working.)
- **Robustness against malformed/hostile bridge responses:** the web-API JSON is
  parsed with a recursion-depth limit and an 8 MiB response cap; a non-numeric
  reverse-control value no longer tears down the TCP connection; the TCP connect
  now has a timeout.
- **Internal clean-up:** the near-identical `sensor` / `binary_sensor` platform
  setup is now a single shared helper, and `system_health` no longer assumes the
  entry is loaded. No user-visible change from these.

## 0.5.7 — 2026-06-01

- **Imported devices now appear under their own "Plan44 device" sub-entry**
  instead of the generic "Devices that don't belong to a sub-entry" section.
  Their entities are added with `config_subentry_id`, so each imported device
  is attributed to the sub-entry that created it. This cleanly separates the
  two directions in the UI: **Virtual device** sub-entries are HA → plan44
  (export), **Plan44 device** sub-entries are plan44 → HA (import) — and the
  same device no longer shows up twice.
- Renamed the import sub-entry type from "P44 device" to **"Plan44 device"**
  (incl. the discovery notification that points at the import button) for a
  clearer, consistent label.

> The "Devices that don't belong to a sub-entry" heading itself is a Home
> Assistant core string and can't be renamed by an integration — but with this
> change plan44 no longer puts anything there.

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
