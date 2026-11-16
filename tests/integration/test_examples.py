"""Every file in examples/ (and the tutorial steps in examples/tutorial/) must start against the real host, reach app.ready and stop cleanly.

Readiness is observed from the SDK's own trace record (``rpc.completed`` for ``app.ready``).
POSIX: SIGTERM to the launcher (documented exit 143). Windows: the launcher is killed
outright, which must take the host and backend down with it (job object), leaving no orphans.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from test_real_host import DESKTOP, EXPORT_HOST, HOST, INSTALLED, SRC, _marker_processes

_ROOT = Path(__file__).resolve().parents[2] / "examples"
EXAMPLES = sorted(_ROOT.glob("*.py")) + sorted((_ROOT / "tutorial").glob("*.py"))
pytestmark = pytest.mark.skipif(not HOST, reason="BLOCKED: no host (set NATIVEHTMLKIT_HOST_BINARY)")


@pytest.mark.parametrize("example", EXAMPLES, ids=[p.relative_to(_ROOT).with_suffix("").as_posix() for p in EXAMPLES])
def test_example_reaches_ready_and_stops(tmp_path, example):
    marker = uuid.uuid4().hex[:12]
    diag = tmp_path / "diag"
    env = {k: v for k, v in os.environ.items() if not k.startswith("UI4ME_")}
    env.update(NATIVEHTMLKIT_DIAGNOSTICS="trace", NATIVEHTMLKIT_DIAGNOSTICS_DIR=str(diag), NHK_IT_MARKER=marker,
               NATIVEHTMLKIT_DIAGNOSTIC_SESSION_ID=f"ex-{marker}")
    if EXPORT_HOST:
        env["NATIVEHTMLKIT_HOST_BINARY"] = HOST
    if not INSTALLED:
        env["PYTHONPATH"] = str(SRC)
    if not DESKTOP:
        env["NATIVEHTMLKIT_TEST_MODE"] = "1"
    options = {"start_new_session": True} if os.name == "posix" else {"creationflags": 0x00000200}
    proc = subprocess.Popen([sys.executable, str(example)], cwd=tmp_path, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, **options)
    ready, deadline = False, time.monotonic() + 30
    while not ready and time.monotonic() < deadline and proc.poll() is None:
        for file in diag.glob("python-*.jsonl") if diag.exists() else []:
            for line in file.read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                if record["event"] == "rpc.completed" and record["context"].get("method") == "app.ready" \
                        and not record["context"].get("failed"):
                    ready = True
        time.sleep(0.1)
    if os.name == "posix":
        proc.send_signal(signal.SIGTERM)
    else:
        proc.kill()
    stdout, stderr = proc.communicate(timeout=30)
    (tmp_path / "stderr.txt").write_bytes(stderr)
    assert ready, f"{example.name} never reached app.ready\n{stderr.decode(errors='replace')[-2000:]}"
    if os.name == "posix":
        assert proc.returncode == 128 + signal.SIGTERM, proc.returncode
        assert b"Traceback" not in stderr, stderr.decode(errors="replace")[-2000:]
    leftovers = []
    for _ in range(80):
        leftovers = _marker_processes(marker, HOST)
        if os.name == "nt":  # the backend's command line names the example script
            leftovers += _marker_processes(example.name, HOST)
        if not leftovers:
            break
        time.sleep(0.1)
    assert not leftovers, f"orphans after stopping {example.name}: {leftovers}"
