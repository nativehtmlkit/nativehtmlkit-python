"""Read-back behaviour tests for examples/ against the real Core host (headless by default).

Each case runs one ``example_checks`` entry point (see that module) in a host-supervised
backend and asserts that every check it reported passed, that it exited cleanly and that no
host or backend process was left behind.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from test_real_host import HERE, HOST, INSTALLED, SRC, assert_clean, launch

import example_catalog
import example_checks

EXAMPLES = HERE.parents[1] / "examples"
CASES = sorted(name for name, value in vars(example_checks).items()
               if callable(value) and not name.startswith("_") and getattr(value, "__module__", "") == "example_checks")


def test_every_catalog_entry_has_a_behaviour_check():
    expected = {example_catalog.check_name(entry["id"]) for entry in example_catalog.load()}
    missing = sorted(expected - set(CASES))
    assert not missing, f"example_checks.py has no check for: {missing}"
    # Every other check covers a tutorial step.
    strays = sorted(name for name in set(CASES) - expected if not name.startswith("tutorial_"))
    assert not strays, f"checks that match no catalogue id: {strays}"


@pytest.mark.skipif(not HOST, reason="BLOCKED: no host (set NATIVEHTMLKIT_HOST_BINARY)")
@pytest.mark.parametrize("case", CASES)
def test_example_behaviour(tmp_path: Path, case: str):
    path = os.pathsep.join(([] if INSTALLED else [str(SRC)]) + [str(HERE), str(EXAMPLES)])
    run = launch(case, tmp_path, env={"PYTHONPATH": path},
                 command=[sys.executable, "-m", "nativehtmlkit", "run", f"example_checks:{case}",
                          "--name", f"Example check {case}"])
    assert_clean(run)
    assert run.checks, f"{case} reported no checks\n{run.stderr[-3000:]}"
    assert "Traceback" not in run.stderr, run.stderr[-3000:]
