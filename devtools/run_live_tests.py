from __future__ import annotations

import os
import subprocess
from pathlib import Path


def main() -> int:
    env_file = Path("devtools/.env.live")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key, value)

    command = ["pytest", "-m", "live_p44", "tests/live", "-vv"]
    return subprocess.call(command, env=os.environ.copy())


if __name__ == "__main__":
    raise SystemExit(main())
