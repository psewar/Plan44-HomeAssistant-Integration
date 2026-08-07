"""Unit tests for the hardened bridge-API SSH client (no network, no HA)."""

from __future__ import annotations

from custom_components.plan44.bridge_client import (
    HEALTHY_SESSION_SECONDS,
    RECONNECT_MAX_SECONDS,
    RECONNECT_MIN_SECONDS,
    pinned_known_hosts,
)

_KEY_LINE = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleKeyDataOnlyForTests"


def test_pinned_known_hosts_format() -> None:
    """The pin must be valid known_hosts content restricted to one key."""
    out = pinned_known_hosts(_KEY_LINE)
    assert isinstance(out, bytes)
    assert out == f"* {_KEY_LINE}\n".encode()


def test_pinned_known_hosts_strips_whitespace() -> None:
    """A key pasted/stored with stray whitespace still yields one clean line."""
    out = pinned_known_hosts(f"  {_KEY_LINE}\n ").decode()
    assert out == f"* {_KEY_LINE}\n"
    assert out.count("\n") == 1


def test_backoff_bounds_are_sane() -> None:
    """A short-lived session must not be able to spin at the minimum delay."""
    assert RECONNECT_MIN_SECONDS < RECONNECT_MAX_SECONDS
    # A session must outlive the minimum reconnect delay before it counts as
    # healthy, otherwise connect->EOF->connect would reset the backoff forever.
    assert HEALTHY_SESSION_SECONDS > RECONNECT_MIN_SECONDS
