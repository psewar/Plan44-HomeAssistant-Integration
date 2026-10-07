"""Unit tests for the hardened bridge-API SSH client (no network, no HA)."""

from __future__ import annotations

import logging

from custom_components.plan44.bridge_client import (
    HEALTHY_SESSION_SECONDS,
    LINK_DOWN_WARNING_ATTEMPTS,
    RECONNECT_MAX_SECONDS,
    RECONNECT_MIN_SECONDS,
    link_down_log_level,
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


def test_self_healed_blip_does_not_warn() -> None:
    """A drop that reconnects on the next attempt must not raise an alarm."""
    assert link_down_log_level(1, already_warned=False) == logging.INFO


def test_failed_reconnect_warns() -> None:
    """Once a reconnect has actually failed, the outage becomes a warning."""
    assert (
        link_down_log_level(LINK_DOWN_WARNING_ATTEMPTS, already_warned=False)
        == logging.WARNING
    )


def test_long_outage_warns_only_once() -> None:
    """A dead tunnel must stay visible without flooding the log every retry."""
    assert link_down_log_level(50, already_warned=True) == logging.DEBUG


def test_warning_threshold_needs_a_failed_retry() -> None:
    """Warning after the first drop would defeat the purpose of the threshold."""
    assert LINK_DOWN_WARNING_ATTEMPTS >= 2
