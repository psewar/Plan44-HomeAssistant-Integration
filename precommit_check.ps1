$ErrorActionPreference = "Stop"

ruff check . --fix
ruff format .
pyright
pytest tests/unit -q

Write-Host ""
Write-Host "Note: the HA component tests (pytest -c pytest.ha.ini) are Linux-only and"
Write-Host "were NOT run. Run ./precommit_check.sh in WSL to cover them before pushing."
