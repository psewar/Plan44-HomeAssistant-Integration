$ErrorActionPreference = "Stop"

ruff check . --fix
ruff format .
pyright
pytest tests/unit -q
