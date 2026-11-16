"""Every example in examples/catalog.toml (and every tutorial step) must start against the real host, reach app.ready and stop cleanly.

The catalogue is the list of examples: ``test_catalog_*`` fail when an entry is incomplete, when
its file is missing, or when a program under examples/ is neither a catalogue entry, a tutorial
step nor a declared helper module.

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

import example_catalog
from test_real_host import DESKTOP, EXPORT_HOST, HOST, INSTALLED, SRC, _marker_processes

_ROOT = example_catalog.EXAMPLES
EXAMPLES = [_ROOT / name for name in example_catalog.runnable_files()]
needs_host = pytest.mark.skipif(not HOST, reason="BLOCKED: no host (set NATIVEHTMLKIT_HOST_BINARY)")


def test_catalog_entries_are_complete_and_unique():
    entries = example_catalog.load()
    ids = [entry["id"] for entry in entries]
    assert len(ids) == len(set(ids)), ids
    for entry in entries:
        missing = example_catalog.REQUIRED_KEYS - entry.keys()
        assert not missing, (entry.get("id"), missing)
        assert (_ROOT / entry["file"]).is_file(), entry["file"]
        assert f"uv run {entry['file']}" in entry["run"], entry


def test_every_program_is_catalogued():
    known = set(example_catalog.runnable_files()) | set(example_catalog.HELPERS)
    uncovered = [name for name in example_catalog.python_files_on_disk() if name not in known]
    assert not uncovered, f"add these to examples/catalog.toml (or TUTORIAL_STEPS/HELPERS): {uncovered}"
    assert all((_ROOT / name).is_file() for name in known), sorted(n for n in known if not (_ROOT / n).is_file())


@needs_host
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
    log = tmp_path / "example.log"
    log.write_text("INFO started\n", encoding="utf-8")
    args = [a.replace("{log}", str(log)) for a in example_catalog.START_ARGS.get(example.relative_to(_ROOT).as_posix(), [])]
    proc = subprocess.Popen([sys.executable, str(example), *args], cwd=tmp_path, env=env, stdout=subprocess.PIPE,
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
