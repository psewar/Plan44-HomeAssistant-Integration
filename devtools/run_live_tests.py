from __future__ import annotations

import os
import subprocess
from pathlib import Path


def main() -> int:
    env = os.environ.copy()

    env_file = Path("devtools/.env.live")
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env.setdefault(key, value)

    repo_root = str(Path(__file__).resolve().parents[1])
    current_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        repo_root
        if not current_pythonpath
        else f"{repo_root}{os.pathsep}{current_pythonpath}"
    )

    command = [
        "pytest",
        "-c",
        "pytest.live.ini",
        "tests/live",
        "-vv",
        "-s",
    ]
    return subprocess.call(command, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
