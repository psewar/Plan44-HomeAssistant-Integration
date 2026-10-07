"""Unit tests for the REST reconnect throttle (no network, no HA)."""

from __future__ import annotations

from custom_components.plan44.coordinator import (
    HEALTHY_SESSION_SECONDS,
    MAX_RECONNECT_DELAY_SECONDS,
    reconnect_throttle,
)

BASE = 5


def test_first_connect_is_immediate() -> None:
    """With no previous session there is nothing to back off from."""
    assert reconnect_throttle(None, BASE, 0) == 0


def test_healthy_session_reconnects_at_once() -> None:
    """A link that stayed up for hours and dropped must come back immediately."""
    assert reconnect_throttle(7200.0, BASE, 0) == 0


def test_session_at_the_threshold_counts_as_healthy() -> None:
    """The threshold itself must not be treated as a failed session."""
    assert reconnect_throttle(float(HEALTHY_SESSION_SECONDS), BASE, 0) == 0


def test_instant_drop_backs_off() -> None:
    """A bridge that accepts and drops the socket must not be hammered."""
    assert reconnect_throttle(0.013, BASE, 0) == BASE


def test_repeated_instant_drops_double_the_delay() -> None:
    """Each further failed session widens the gap instead of spinning."""
    assert reconnect_throttle(0.013, BASE, BASE) == BASE * 2
    assert reconnect_throttle(0.013, BASE, BASE * 2) == BASE * 4


def test_backoff_is_capped() -> None:
    """A long outage must not grow the delay without bound."""
    assert (
        reconnect_throttle(0.013, BASE, MAX_RECONNECT_DELAY_SECONDS)
        == MAX_RECONNECT_DELAY_SECONDS
    )


def test_healthy_session_clears_a_previous_backoff() -> None:
    """Once the bridge serves properly again, the next drop is not penalised."""
    assert reconnect_throttle(3600.0, BASE, MAX_RECONNECT_DELAY_SECONDS) == 0


def test_a_boot_storm_needs_few_attempts() -> None:
    """Replay of the 2026-09-05 bridge reboot: ~338s of connect/EOF churn.

    Before the throttle this produced 4133 reconnects; the doubling delay must
    get through the same outage in a handful of attempts.
    """
    elapsed = 0.0
    delay = 0
    attempts = 0
    while elapsed < 338.0:
        delay = reconnect_throttle(0.013, BASE, delay)
        elapsed += delay
        attempts += 1
    assert attempts <= 10
