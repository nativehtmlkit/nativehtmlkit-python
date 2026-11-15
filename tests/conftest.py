"""Make the suite import this checkout's ``src`` tree (never an unrelated installed copy).

Set ``NATIVEHTMLKIT_TEST_INSTALLED=1`` to deliberately exercise an installed distribution
instead (used by the clean-install smoke test).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if os.environ.get("NATIVEHTMLKIT_TEST_INSTALLED") != "1":
    sys.path.insert(0, str(SRC))
