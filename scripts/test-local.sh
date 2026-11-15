#!/usr/bin/env bash
# Local unit/fake-host suite (P0). Uses $PYTHON (default python3); if that interpreter has no
# pytest, runs it through `uv run --with pytest` instead (uv may need its cache or network once).
# Real-host tests: set NATIVEHTMLKIT_HOST_BINARY (see scripts/qualify.py).
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON=${PYTHON:-python3}
"$PYTHON" -m compileall -q src/nativehtmlkit
if "$PYTHON" -c "import pytest, pytest_timeout" >/dev/null 2>&1; then
  exec "$PYTHON" -m pytest -q -p no:cacheprovider tests "$@"
elif command -v uv >/dev/null 2>&1; then
  exec uv run --no-project --python "$PYTHON" --with pytest --with pytest-timeout \
    python -m pytest -q -p no:cacheprovider tests "$@"
else
  echo "test-local: $PYTHON has no pytest/pytest-timeout and uv is not installed" >&2
  exit 2
fi
