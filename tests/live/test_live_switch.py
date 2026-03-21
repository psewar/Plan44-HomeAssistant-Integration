from __future__ import annotations

import pytest

from plan44_core.models import SwitchState, VirtualDeviceSpec


@pytest.mark.live_p44
async def test_live_switch_roundtrip(live_harness) -> None:
    spec = VirtualDeviceSpec(
        device_id="test::switch.live",
        name="Live Test Switch",
        kind="switch",
    )
    await live_harness.provision([spec])
    await live_harness.set_state(spec, SwitchState(is_on=True))
