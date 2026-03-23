#!/usr/bin/env bash
set -euo pipefail

ruff check . --fix
ruff format .
pyright
pytest tests/unit -q
