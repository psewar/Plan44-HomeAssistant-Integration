from __future__ import annotations

from plan44_core.protocol import build_log_message


def test_build_log_message_defaults() -> None:
    assert build_log_message("ha keepalive") == {
        "message": "log",
        "level": 7,
        "text": "ha keepalive",
    }


def test_build_log_message_level_override() -> None:
    msg = build_log_message("boom", level=3)
    assert msg == {"message": "log", "level": 3, "text": "boom"}
