"""system_health must register its info callback synchronously.

Regression guard: Home Assistant's system_health calls ``async_register``
*without awaiting it*, so it has to be a sync ``@callback``. If it were an
``async def``, the returned coroutine would be discarded, ``async_register_info``
would never run, and the registration's ``info_callback`` would stay ``None`` —
which makes HA raise ``AssertionError`` for plan44 when the System Health panel
is opened.
"""

from __future__ import annotations

import inspect
from unittest.mock import MagicMock

from custom_components.plan44 import system_health


def test_async_register_is_sync_and_registers_info() -> None:
    assert not inspect.iscoroutinefunction(system_health.async_register)

    register = MagicMock()
    result = system_health.async_register(MagicMock(), register)

    assert result is None
    register.async_register_info.assert_called_once_with(
        system_health.system_health_info
    )
