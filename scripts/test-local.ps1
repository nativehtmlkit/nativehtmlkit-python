# Local unit/fake-host suite (P0) on Windows (Windows PowerShell 5.1 or PowerShell 7).
# Uses $env:PYTHON (default: python); falls back to `uv run --with pytest` when that
# interpreter lacks pytest. Native-command stderr must not become a terminating error
# (PS 5.1 + ErrorActionPreference=Stop), so exit codes are checked explicitly instead.
Set-Location (Split-Path -Parent $PSScriptRoot)
$ErrorActionPreference = 'Continue'
$py = if ($env:PYTHON) { $env:PYTHON } else { 'python' }
& $py -m compileall -q src/nativehtmlkit
if ($LASTEXITCODE -ne 0) { Write-Error 'compileall failed'; exit 1 }
& $py -c 'import pytest, pytest_timeout' 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    & $py -m pytest -q -p no:cacheprovider tests @args
} else {
    uv run --no-project --python $py --with pytest --with pytest-timeout python -m pytest -q -p no:cacheprovider tests @args
}
exit $LASTEXITCODE
