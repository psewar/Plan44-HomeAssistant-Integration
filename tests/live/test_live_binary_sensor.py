from __future__ import annotations

import pytest
from plan44_core.models import BinarySensorState, VirtualDeviceSpec


@pytest.mark.live_p44
async def test_live_binary_sensor_roundtrip(live_harness) -> None:
    spec = VirtualDeviceSpec(
        device_id="test::binary_sensor.live",
        name="Live Test Contact",
        kind="binary_sensor",
        input_type=0,
        input_usage=2,
        input_group=8,
        input_update_interval=60,
        input_alive_sign_interval=300,
    )
    await live_harness.provision([spec])
    await live_harness.assert_no_error_status()

    await live_harness.set_state(spec, BinarySensorState(is_on=True))
    await live_harness.assert_no_error_status()
