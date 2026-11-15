#!/usr/bin/env python3
"""Qualification runner for the Python SDK against ONE exact prebuilt Core host.

Runs on the machine under test and records machine-readable results (PASS / FAIL /
BLOCKED) into ``--results`` (merged by id), with logs beside it:

    python scripts/qualify.py --host PATH --host-sha256 HEX --evidence DIR \\
        [--python 3.10 --python 3.14] [--stages unit,contract,integration,package,smoke,gui] \\
        [--core-protocol DIR] [--core-notices DIR] [--desktop] [--label NAME]

Stages:
  unit         G0/G2  scripts/test-local.* per interpreter (fake host, framing, contract pin)
  contract     G2     contracts/ snapshot == Core's published protocol/v1/method-matrix.json
  integration  G3/G4/G7  tests/integration against the real host (headless unless --desktop),
               one result per test (junit)
  package      G8     scripts/package-local.py for this platform's host (fail-closed SHA)
  smoke        G8     scripts/smoke-installed.py: fresh venv, offline wheel install, real host
  gui          G6     tests/native/gui_driver.py (must run INSIDE the interactive desktop)
A stage whose prerequisite is missing is BLOCKED with the reason; a failed assertion is FAIL.
"""
from __future__ import annotations

import argparse
import json
import os
import platform as _platform
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from provenance import ROOT, file_sha256, source_tree_sha256  # noqa: E402

WINDOWS = os.name == "nt"
PLATFORM = "windows-x64" if WINDOWS else "linux-x64"
G4_TESTS = ("callbacks", "killed", "malformed", "submit_did_nothing", "overflow", "session_id")


class Recorder:
    def __init__(self, path: Path, evidence: Path, label: str, host_sha: str):
        self.path, self.evidence, self.label, self.host_sha = path, evidence, label, host_sha
        self.tree = source_tree_sha256()
        self.entries = json.loads(path.read_text()) if path.exists() else []

    def add(self, id_: str, gate: str, status: str, command, duration: float, exit_code, log: Path | None, **extra):
        assert status in ("PASS", "FAIL", "BLOCKED")
        entry = {"id": f"{self.label}:{id_}", "gate": gate, "status": status,
                 "command": command if isinstance(command, str) else " ".join(map(str, command)),
                 "platform": self.label, "source_tree_sha256": self.tree, "host_sha256": self.host_sha,
                 "duration_s": round(duration, 2), "exit_code": exit_code,
                 "log": str(log.relative_to(self.evidence)) if log else None, **extra}
        self.entries = [e for e in self.entries if e["id"] != entry["id"]] + [entry]
        self.path.write_text(json.dumps(self.entries, indent=2), encoding="utf-8")
        print(f"{status:8} {gate:3} {entry['id']}", flush=True)


def run(command, log: Path, *, env=None, cwd=ROOT, timeout=3600):
    started = time.monotonic()
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8", errors="replace") as handle:
        handle.write("$ " + " ".join(map(str, command)) + "\n")
        handle.flush()
        try:
            code = subprocess.run([str(c) for c in command], cwd=cwd, env=env, stdout=handle, stderr=subprocess.STDOUT,
                                  timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = None
            handle.write(f"\nTIMEOUT after {timeout}s\n")
    return code, time.monotonic() - started


def interpreter(version: str) -> str | None:
    out = subprocess.run(["uv", "python", "find", version], capture_output=True, text=True)
    return out.stdout.strip() or None


def pytest_counts(log: Path) -> dict:
    text = log.read_text(encoding="utf-8", errors="replace")
    return {k: int(v) for v, k in re.findall(r"(\d+) (passed|failed|skipped|error)", text.splitlines()[-1] if text else "")}


def stage_unit(rec: Recorder, args):
    for version in args.python:
        python = interpreter(version)
        log = rec.evidence / "logs" / f"{rec.label}-unit-{version}.log"
        if not python:
            rec.add(f"unit-py{version}", "G0", "BLOCKED", f"uv python find {version}", 0, None, None,
                    reason=f"interpreter {version} not available via uv")
            continue
        script = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ROOT / "scripts/test-local.ps1"] \
            if WINDOWS else ["bash", ROOT / "scripts/test-local.sh"]
        env = {k: v for k, v in os.environ.items() if k != "NATIVEHTMLKIT_HOST_BINARY"}
        env["PYTHON"] = python
        code, seconds = run(script + ["-rs", "--ignore=tests/integration"], log, env=env)
        counts = pytest_counts(log)
        rec.add(f"unit-py{version}", "G0", "PASS" if code == 0 and counts.get("passed") else "FAIL",
                f"PYTHON={python} scripts/test-local -rs --ignore=tests/integration", seconds, code, log,
                counts=counts, interpreter=version)


def stage_contract(rec: Recorder, args):
    pinned = json.loads((ROOT / "contracts/SOURCE.json").read_text())["sha256"]
    snapshot = file_sha256(ROOT / "contracts/core-v1-method-matrix.json")
    candidates = [Path(args.core_protocol) / "v1/method-matrix.json"] if args.core_protocol else []
    candidates.append(Path(args.host).parent / "protocol/v1/method-matrix.json")
    core = next((c for c in candidates if c.is_file()), None)
    if core is None:
        rec.add("contract-matrix", "G2", "BLOCKED", "compare method-matrix.json", 0, None, None,
                reason="no Core protocol/v1/method-matrix.json beside the host or via --core-protocol",
                snapshot_sha256=snapshot, pinned_sha256=pinned)
        return
    actual = file_sha256(core)
    ok = actual == snapshot == pinned
    rec.add("contract-matrix", "G2", "PASS" if ok else "FAIL", f"sha256 {core}", 0, 0 if ok else 1, None,
            core_matrix_sha256=actual, snapshot_sha256=snapshot, pinned_sha256=pinned)


def stage_integration(rec: Recorder, args):
    python = interpreter(args.python[-1]) or sys.executable
    junit = rec.evidence / "logs" / f"{rec.label}-integration.xml"
    log = rec.evidence / "logs" / f"{rec.label}-integration.log"
    env = dict(os.environ, NATIVEHTMLKIT_HOST_BINARY=str(Path(args.host).resolve()))
    if args.desktop:
        env["NHK_IT_DESKTOP"] = "1"
    command = ["uv", "run", "--no-project", "--python", python, "--with", "pytest", "--with", "pytest-timeout",
               "python", "-m", "pytest", "-p", "no:cacheprovider", "-rs", "--junitxml", junit,
               "--basetemp", rec.evidence / f"it-{rec.label}", "tests/integration"]
    code, seconds = run(command, log, env=env)
    if not junit.exists():
        rec.add("integration", "G3", "FAIL", command, seconds, code, log, reason="pytest produced no junit report")
        return
    for case in ET.parse(junit).getroot().iter("testcase"):
        name = case.get("name")
        gate = "G4" if any(t in name for t in G4_TESTS) else "G3"
        if case.find("skipped") is not None:
            status, reason = "BLOCKED", (case.find("skipped").get("message") or "")[:300]
        elif case.find("failure") is not None or case.find("error") is not None:
            node = case.find("failure") if case.find("failure") is not None else case.find("error")
            status, reason = "FAIL", (node.get("message") or "")[:500]
        else:
            status, reason = "PASS", None
        rec.add(f"it-{name}", gate, status, f"pytest tests/integration -k '{name}'", float(case.get("time", 0)),
                code, log, mode="desktop" if args.desktop else "headless", **({"reason": reason} if reason else {}))


def stage_package(rec: Recorder, args):
    out = rec.evidence / f"dist-{rec.label}"
    if out.exists():
        import shutil
        shutil.rmtree(out)
    command = [sys.executable, ROOT / "scripts/package-local.py", "--out", out,
               "--host", f"{PLATFORM}={Path(args.host).resolve()}={args.host_sha256}"]
    if args.core_notices:
        command += ["--core-notices", args.core_notices]
    if args.core_version:
        command += ["--core-version", args.core_version]
    if args.sdist:
        command.append("--sdist")
    log = rec.evidence / "logs" / f"{rec.label}-package.log"
    code, seconds = run(command, log)
    wheels = sorted(out.glob("*.whl")) if code == 0 else []
    rec.add("package", "G8", "PASS" if wheels else "FAIL", command, seconds, code, log,
            artifacts=(json.loads((out / "dist-manifest.json").read_text())["artifacts"] if wheels else []))
    args.wheel = wheels[0] if wheels else None


def stage_smoke(rec: Recorder, args):
    wheel = getattr(args, "wheel", None) or (Path(args.wheel_path) if args.wheel_path else None)
    if not wheel or not wheel.exists():
        rec.add("smoke", "G8", "BLOCKED", "smoke-installed.py", 0, None, None, reason="no wheel (run the package stage)")
        return
    out = rec.evidence / f"smoke-{rec.label}"
    command = [sys.executable, ROOT / "scripts/smoke-installed.py", "--wheel", wheel, "--expected-host-sha",
               args.host_sha256, "--out", out] + sum((["--python", v] for v in args.python), [])
    if args.desktop:
        command.append("--desktop")
    log = rec.evidence / "logs" / f"{rec.label}-smoke.log"
    code, seconds = run(command, log)
    report = json.loads((out / "smoke-results.json").read_text()) if (out / "smoke-results.json").exists() else {}
    for r in report.get("reports", []):
        failed = [k for k, v in r["checks"].items() if not v]
        rec.add(f"smoke-py{r['python_request']}", "G8", "PASS" if r["checks"] and not failed else "FAIL", command,
                seconds, code, log, failed=failed, integration=r.get("integration_summary"),
                mode="desktop" if args.desktop else "headless")
    if not report:
        rec.add("smoke", "G8", "FAIL", command, seconds, code, log, reason="no smoke report")


def stage_gui(rec: Recorder, args):
    out = rec.evidence / f"gui-{rec.label}"
    command = [sys.executable, ROOT / "tests/native/gui_driver.py", "--out", out, "--host", Path(args.host).resolve()]
    if args.gui_python:
        command += ["--python", args.gui_python]
    log = rec.evidence / "logs" / f"{rec.label}-gui.log"
    code, seconds = run(command, log, cwd=ROOT / "tests/native", timeout=900)
    results = out / "results.json"
    if not results.exists():
        rec.add("gui", "G6", "FAIL", command, seconds, code, log, reason="driver wrote no results (not in a desktop?)")
        return
    data = json.loads(results.read_text())
    if data.get("blocked"):
        rec.add("gui", "G6", "BLOCKED", command, seconds, code, log, reason=data["reason"][:400])
        return
    for name, check in sorted(data["checks"].items()):
        detail = {k: v for k, v in check.items() if k not in ("kind", "t", "name", "status")}
        rec.add(f"gui-{name}", "G6" if not name.startswith(("privacy", "diagnostics")) else "G4",
                "PASS" if check["status"] == "pass" else "FAIL", command, seconds, code, log,
                session=data["session_env"], detail=json.dumps(detail, default=repr)[:400])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", required=True)
    parser.add_argument("--host-sha256", required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--results", type=Path, help="default: EVIDENCE/results.json")
    parser.add_argument("--label", default=f"{PLATFORM}")
    parser.add_argument("--python", action="append", help="interpreter versions (default: 3.10 and 3.14)")
    parser.add_argument("--stages", default="unit,contract,integration,package,smoke")
    parser.add_argument("--core-protocol")
    parser.add_argument("--core-notices")
    parser.add_argument("--core-version")
    parser.add_argument("--sdist", action="store_true")
    parser.add_argument("--wheel-path")
    parser.add_argument("--gui-python")
    parser.add_argument("--desktop", action="store_true", help="integration/smoke with real windows")
    args = parser.parse_args(argv)
    args.python = args.python or ["3.10", "3.14"]
    args.evidence = args.evidence.resolve()
    args.evidence.mkdir(parents=True, exist_ok=True)
    host = Path(args.host)
    if not host.is_file():
        print(f"qualify: host not found: {host}", file=sys.stderr)
        return 2
    actual = file_sha256(host)
    rec = Recorder((args.results or args.evidence / "results.json").resolve(), args.evidence, args.label, actual)
    if actual != args.host_sha256.lower():
        rec.add("host-pin", "G8", "FAIL", f"sha256 {host}", 0, 1, None, expected=args.host_sha256, actual=actual)
        return 1
    rec.add("host-pin", "G8", "PASS", f"sha256 {host}", 0, 0, None, machine=_platform.node(), python=sys.version.split()[0])
    stages = {"unit": stage_unit, "contract": stage_contract, "integration": stage_integration,
              "package": stage_package, "smoke": stage_smoke, "gui": stage_gui}
    for name in args.stages.split(","):
        stages[name.strip()](rec, args)
    mine = [e for e in rec.entries if e["platform"] == rec.label]
    summary = {s: sum(1 for e in mine if e["status"] == s) for s in ("PASS", "FAIL", "BLOCKED")}
    print(json.dumps(summary))
    return 0 if summary["FAIL"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
