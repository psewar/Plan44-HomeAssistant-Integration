from __future__ import annotations

import pytest

from plan44_core.models import LightState, VirtualDeviceSpec


@pytest.mark.live_p44
async def test_live_light_roundtrip(live_harness) -> None:
    spec = VirtualDeviceSpec(
        device_id="test::light.live",
        name="Live Test Light",
        kind="light",
    )
    await live_harness.provision([spec])
    await live_harness.set_state(spec, LightState(is_on=True, brightness=128))
