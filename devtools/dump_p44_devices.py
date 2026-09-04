#!/usr/bin/env python3
"""Dump devices from a plan44 bridge and emit HA template stubs.

Two transports:

* **HTTP(S) web API (mg44)** — for a bridge reachable via its web UI URL.
  The mg44 server wraps an HTTP POST to ``<url>/api/vdc`` into a vdc-API
  ``getProperty`` request.  Auth is HTTP Digest; credentials come from the
  environment (``P44_USER`` / ``P44_PASSWORD``) so they never appear on the
  command line or in this chat.  Self-signed certs are accepted.

* **Raw TCP JSON API** — newline-delimited JSON to the vdSM/bridge API port.

Enumeration uses a getProperty query over ``x-p44-vdcs`` / ``x-p44-devices``
that returns each device's sensor/input descriptions, from which template
stubs for ``custom_components/plan44/device_templates.py`` are generated.

Usage (HTTP, credentials from devtools/.env.p44):
    set -a; . devtools/.env.p44; set +a
    python devtools/dump_p44_devices.py --url "$P44_URL"
    python devtools/dump_p44_devices.py --url "$P44_URL" --out devtools/devices.json
    python devtools/dump_p44_devices.py --from-file devtools/devices.json

Usage (raw TCP):
    python devtools/dump_p44_devices.py --host 192.0.2.10 --port 8440
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

ENUM_REQUEST: dict[str, Any] = {
    "method": "getProperty",
    "dSUID": "",  # empty/invalid dSUID addresses the vdc host itself
    "query": {
        "x-p44-vdcs": {
            "*": {
                "dSUID": None,
                "name": None,
                "x-p44-devices": {
                    "*": {
                        "dSUID": None,
                        "name": None,
                        "model": None,
                        "vendorName": None,
                        "x-p44-deviceHardwareId": None,
                        "x-p44-bridgeable": None,
                        "active": None,
                        "sensorDescriptions": None,
                        "binaryInputDescriptions": None,
                        "buttonInputDescriptions": None,
                        "outputDescription": None,
                    }
                },
            }
        }
    },
}


# --------------------------------------------------------------------------
# Transports
# --------------------------------------------------------------------------


def fetch_http(url: str, timeout: float) -> Any:
    """POST the getProperty request to <url>/api/json/vdc with Digest auth.

    Mirrors the plan44 web UI (p44api.js): optional CSRF token from /tok/json
    appended as ?rqvaltok=..., then POST the vdc-API request as the body.
    """
    user = os.environ.get("P44_USER")
    password = os.environ.get("P44_PASSWORD")
    if not user or not password:
        print(
            "ERROR: set P44_USER and P44_PASSWORD (e.g. `set -a; . devtools/.env.p44; "
            "set +a`) — they are read from the environment, never the command line.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    base = url.rstrip("/")

    # self-signed cert on local plan44 device → do not verify
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    pwmgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    pwmgr.add_password(None, base, user, password)  # covers all paths on host
    opener = urllib.request.build_opener(
        urllib.request.HTTPDigestAuthHandler(pwmgr),
        urllib.request.HTTPSHandler(context=ctx),
    )

    # CSRF token: GET /tok/json (404 => CSRF disabled, no token needed)
    token = None
    try:
        with opener.open(base + "/tok/json", timeout=timeout) as tr:
            token = json.loads(tr.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        if err.code != 404:
            raise

    endpoint = base + "/api/json/vdc"
    if token not in (None, True, False):
        endpoint += "?rqvaltok=" + urllib.parse.quote(str(token))

    body = json.dumps(ENUM_REQUEST).encode("utf-8")
    req = urllib.request.Request(
        endpoint, data=body, headers={"Content-Type": "application/json"}
    )
    print(
        f"POST {base}/api/json/vdc (digest as {user}, csrf={'yes' if token else 'no'})",
        file=sys.stderr,
    )
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


async def fetch_tcp(host: str, port: int, timeout: float, idle: float) -> list[Any]:
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port), timeout
    )
    print(f"connected to {host}:{port}", file=sys.stderr)
    writer.write((json.dumps(ENUM_REQUEST) + "\n").encode("utf-8"))
    await writer.drain()
    objects: list[Any] = []
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=idle)
        except TimeoutError:
            break
        if not raw:
            break
        line = raw.decode("utf-8", errors="ignore").strip()
        if line:
            try:
                objects.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"  (non-JSON ignored: {line[:80]!r})", file=sys.stderr)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass
    return objects


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------


def find_devices(payload: Any) -> dict[str, dict[str, Any]]:
    """Recursively collect device-looking dicts (dSUID + descriptions/model)."""
    devices: dict[str, dict[str, Any]] = {}

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if "dSUID" in node and any(
                k in node
                for k in ("sensorDescriptions", "binaryInputDescriptions", "model")
            ):
                devices[str(node["dSUID"])] = node
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    visit(payload)
    return devices


def descr_items(descriptions: Any) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(descriptions, dict):
        return [(str(k), v) for k, v in descriptions.items() if isinstance(v, dict)]
    if isinstance(descriptions, list):
        return [(str(i), v) for i, v in enumerate(descriptions) if isinstance(v, dict)]
    return []


def print_summary(devices: dict[str, dict[str, Any]]) -> None:
    if not devices:
        print("\nNo devices found. Re-run with --raw to inspect the response.")
        return
    print(f"\n=== {len(devices)} device(s) ===\n")
    for dsuid, dev in devices.items():
        print(f"- {dev.get('name') or '(unnamed)'}  [{dev.get('model') or '?'}]")
        hwid = dev.get("x-p44-deviceHardwareId")
        if hwid:
            print(f"    tag/hardwareId: {hwid}")
        print(f"    dSUID: {dsuid}")
        for idx, d in descr_items(dev.get("sensorDescriptions")):
            print(
                f"    sensor[{idx}]: {d.get('name', '?')} "
                f"type={d.get('sensorType')} unit={d.get('siunit') or d.get('symbol')}"
            )
        for idx, d in descr_items(dev.get("binaryInputDescriptions")):
            print(f"    input[{idx}]: {d.get('name', '?')}")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description="Dump plan44 devices.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="bridge web UI base URL (HTTPS mg44 API)")
    src.add_argument("--host", help="bridge host/IP (raw TCP JSON API)")
    src.add_argument("--from-file", help="parse a previously dumped JSON file")
    p.add_argument("--port", type=int, default=8440, help="TCP port (raw mode)")
    p.add_argument("--timeout", type=float, default=15.0)
    p.add_argument("--idle", type=float, default=2.0, help="TCP idle stop (s)")
    p.add_argument("--raw", action="store_true", help="print the raw response")
    p.add_argument("--out", help="write the raw response to this file")
    args = p.parse_args()

    if args.from_file:
        with open(args.from_file, encoding="utf-8") as fh:
            payload: Any = json.load(fh)
    elif args.url:
        try:
            payload = fetch_http(args.url, args.timeout)
        except Exception as err:
            print(f"ERROR: {type(err).__name__}: {err}", file=sys.stderr)
            return 2
    else:
        payload = asyncio.run(fetch_tcp(args.host, args.port, args.timeout, args.idle))

    if args.raw:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        print(f"raw response written to {args.out}", file=sys.stderr)

    print_summary(find_devices(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
