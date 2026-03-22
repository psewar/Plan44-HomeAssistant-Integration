from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values


def main() -> int:
    env = os.environ.copy()

    env_file = Path("devtools/.env.live")
    if env_file.exists():
        for key, value in dotenv_values(env_file).items():
            if value is not None:
                env.setdefault(key, value)

    repo_root = str(Path(__file__).resolve().parents[1])
    current_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        repo_root
        if not current_pythonpath
        else f"{repo_root}{os.pathsep}{current_pythonpath}"
    )

    command = [
        sys.executable,
        "-m",
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
