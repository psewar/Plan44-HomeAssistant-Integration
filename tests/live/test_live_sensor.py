from __future__ import annotations

import pytest
from plan44_core.models import SensorState, VirtualDeviceSpec


@pytest.mark.live_p44
async def test_live_sensor_roundtrip(live_harness) -> None:
    spec = VirtualDeviceSpec(
        device_id="test::sensor.live",
        name="Live Test Temperature",
        kind="sensor",
        unit="°C",
        sensor_type=1,
        sensor_min=0,
        sensor_max=100,
        sensor_resolution=0.1,
        sensor_update_interval=60,
    )
    await live_harness.provision([spec])
    await live_harness.assert_no_error_status()

    await live_harness.set_state(spec, SensorState(numeric_value=21.5))
    await live_harness.assert_no_error_status()
