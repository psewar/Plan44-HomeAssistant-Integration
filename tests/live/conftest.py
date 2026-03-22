from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import pytest_asyncio
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

load_dotenv(REPO_ROOT / "devtools" / ".env.live", override=False)

from plan44_core.harness import P44TestHarness, TraceRecorder
from plan44_core.session import P44Session


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "live_p44: test requires a reachable live plan44 bridge",
    )


@pytest.fixture
def live_p44_enabled() -> bool:
    return os.getenv("P44_TEST_ENABLED", "0") == "1"


@pytest.fixture
def live_trace_path(tmp_path: Path) -> Path:
    configured = os.getenv("P44_TRACE_PATH")
    if configured:
        path = Path(configured)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    return tmp_path / "p44_live_trace.jsonl"


@pytest_asyncio.fixture
async def live_harness(live_p44_enabled: bool, live_trace_path: Path):
    if not live_p44_enabled:
        pytest.skip("live P44 tests disabled; set P44_TEST_ENABLED=1")

    host = os.environ["P44_TEST_HOST"]
    port = int(os.getenv("P44_TEST_PORT", "8999"))
    model_name = os.getenv("P44_TEST_MODEL", "plan44_core live tests")

    recorder = TraceRecorder(live_trace_path)
    session = P44Session(
        host=host,
        port=port,
        model_name=model_name,
        trace_hook=recorder,
    )
    harness = P44TestHarness(session)
    await harness.connect()
    try:
        yield harness
    finally:
        await session.disconnect()
