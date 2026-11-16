#!/usr/bin/env python3
"""Clean-install smoke test of a built wheel (G8): fresh venv, offline install, no Rust.

    python scripts/smoke-installed.py --wheel dist/nativehtmlkit-...whl --expected-host-sha HEX \\
        --python 3.10 --python 3.14 --out OUTDIR [--desktop]

Per interpreter: create a new venv, install ONLY the wheel with ``--offline --no-index``
(the package has no dependencies), then from an empty directory with a PATH that has
no Rust toolchain: import, check the installed host's SHA-256 against the expected pin
and its manifest, protocol version, console scripts (and that no ``nativehtmlkit``
executable was installed), scaffold + skill CLIs, and run the real-host integration
scenarios against the wheel's bundled host (headless, or ``--desktop`` for real windows).
Test tooling (pytest) is installed into the venv from the local uv cache only.
Writes ``OUTDIR/smoke-results.json``; exit status 1 if any check failed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WINDOWS = os.name == "nt"


def run(command, *, env=None, cwd=None, timeout=600):
    started = time.monotonic()
    result = subprocess.run([str(c) for c in command], env=env, cwd=cwd, capture_output=True, text=True,
                            timeout=timeout, encoding="utf-8", errors="replace")
    return result, round(time.monotonic() - started, 2)


def clean_env(venv: Path) -> dict:
    scripts = venv / ("Scripts" if WINDOWS else "bin")
    system = [os.environ.get("SystemRoot", r"C:\Windows") + r"\System32", os.environ.get("SystemRoot", r"C:\Windows"),
              r"C:\Windows\System32\WindowsPowerShell\v1.0"] if WINDOWS else ["/usr/bin", "/bin"]
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("UI4ME_", "NATIVEHTMLKIT_", "CARGO", "RUSTUP", "PYTHON", "VIRTUAL_ENV", "UV_"))}
    env["PATH"] = os.pathsep.join([str(scripts)] + system)
    env["VIRTUAL_ENV"] = str(venv)
    env["PYTHONNOUSERSITE"] = "1"
    return env


def smoke(python: str, wheel: Path, expected: str, out: Path, desktop: bool) -> dict:
    report = {"python_request": python, "checks": {}, "logs": {}}
    checks = report["checks"]
    work = Path(tempfile.mkdtemp(prefix=f"nhk-smoke-{python}-"))
    venv = work / "venv"
    result, _ = run(["uv", "venv", "--python", python, str(venv)])
    checks["venv_created"] = result.returncode == 0
    if result.returncode:
        report["logs"]["venv"] = result.stderr[-2000:]
        return report
    interpreter = venv / ("Scripts/python.exe" if WINDOWS else "bin/python")
    result, seconds = run(["uv", "pip", "install", "--python", interpreter, "--offline", "--no-index",
                           "--no-cache", str(wheel)])
    checks["offline_install_wheel_only"] = result.returncode == 0
    report["install_seconds"] = seconds
    report["logs"]["install"] = (result.stdout + result.stderr)[-2000:]
    if result.returncode:
        return report
    env = clean_env(venv)
    empty = work / "empty-cwd"
    empty.mkdir()
    checks["no_rust_toolchain_on_path"] = not any(shutil.which(t, path=env["PATH"]) for t in ("cargo", "rustc"))
    probe = ("import json, sys, nativehtmlkit, nativehtmlkit.client as c; "
             "print(json.dumps({'file': nativehtmlkit.__file__, 'version': nativehtmlkit.__version__, "
             "'client': c.CLIENT_VERSION, 'python': sys.version.split()[0]}))")
    result, _ = run([interpreter, "-I", "-c", probe], env=env, cwd=empty)
    checks["import"] = result.returncode == 0
    if result.returncode == 0:
        info = json.loads(result.stdout)
        report["import"] = info
        checks["imported_from_venv"] = Path(info["file"]).resolve().is_relative_to(venv.resolve())
        checks["versions_agree"] = info["version"] == info["client"]
        report["python"] = info["python"]
    scripts = venv / ("Scripts" if WINDOWS else "bin")
    exe = ".exe" if WINDOWS else ""
    checks["no_competing_nativehtmlkit_executable"] = not (scripts / f"nativehtmlkit{exe}").exists()
    checks["runner_script_installed"] = (scripts / f"nativehtmlkit-python{exe}").exists()
    result, _ = run([scripts / f"nativehtmlkit-python{exe}", "version"], env=env, cwd=empty)
    checks["version_command"] = result.returncode == 0
    if result.returncode == 0:
        version = json.loads(result.stdout)
        report["version"] = version
        host = version["host"]
        checks["host_bundled"] = host["source"] == "bundled"
        checks["host_sha_matches_pin"] = host["sha256"] == expected
        checks["host_manifest_matches"] = host["manifest_match"] is True
        checks["protocol_v1"] = version["protocol_version"] == 1 and host["manifest"]["protocol_version"] == 1
        checks["core_notices_installed"] = (Path(host["path"]).parent / "core-licenses/THIRD_PARTY_NOTICES.md").is_file()
        checks["host_source_identity_matches"] = host.get("source_identity_match") is True
    else:
        report["logs"]["version"] = result.stderr[-2000:]
    project = work / "scaffolded"
    result, _ = run([scripts / f"nativehtmlkit-new{exe}", project, "--name", "Smoke App"], env=env, cwd=empty)
    checks["scaffold_cli"] = result.returncode == 0 and (project / "app.py").is_file()
    skill_project = work / "skill-project"
    skill_project.mkdir()
    skill = [scripts / f"nativehtmlkit-skill{exe}"]
    a, _ = run(skill + ["install", "--scope", "project", "--project", skill_project, "--agents", "claude"], env=env)
    b, _ = run(skill + ["status", "--scope", "project", "--project", skill_project, "--agents", "claude"], env=env)
    c, _ = run(skill + ["uninstall", "--scope", "project", "--project", skill_project, "--agents", "claude"], env=env)
    checks["skill_cli_install_status_uninstall"] = (a.returncode == b.returncode == c.returncode == 0
                                                     and "installed" in b.stdout and "removed" in c.stdout)
    # Test tooling only (not product dependencies), from the local cache.
    result, _ = run(["uv", "pip", "install", "--python", interpreter, "--offline", "pytest", "pytest-timeout"])
    checks["test_tooling_from_cache"] = result.returncode == 0
    if result.returncode == 0:
        test_env = dict(env, NATIVEHTMLKIT_TEST_INSTALLED="1")
        if desktop:
            for key in ("WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS", "DISPLAY", "XDG_SESSION_TYPE",
                        "XDG_CURRENT_DESKTOP"):
                if key in os.environ:
                    test_env[key] = os.environ[key]
            test_env["NHK_IT_DESKTOP"] = "1"
        selection = "api_operations or direct_start or version_and_doctor or asyncio_adapter"
        log = out / f"smoke-{python}-integration.log"
        result, seconds = run([interpreter, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-rs",
                               "--basetemp", work / "it", "-k", selection, ROOT / "tests/integration"],
                              env=test_env, cwd=empty, timeout=900)
        log.write_text(result.stdout + result.stderr, encoding="utf-8")
        report["logs"]["integration"] = str(log)
        tail = (result.stdout.strip().splitlines() or [""])[-1]
        report["integration_summary"] = tail
        import re
        passed = int((re.search(r"(\d+) passed", tail) or [0, 0])[1])
        checks["installed_real_host_scenarios"] = (result.returncode == 0 and passed >= 4 and "failed" not in tail
                                                   and "skipped" not in tail and "error" not in tail)
    shutil.rmtree(work, ignore_errors=True)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--expected-host-sha", required=True)
    parser.add_argument("--python", action="append", required=True, help="interpreter version for uv (repeatable)")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--desktop", action="store_true", help="run the scenarios with real windows")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    reports = [smoke(p, args.wheel.resolve(), args.expected_host_sha.lower(), args.out, args.desktop) for p in args.python]
    ok = all(r["checks"] and all(r["checks"].values()) for r in reports)
    (args.out / "smoke-results.json").write_text(json.dumps({"wheel": args.wheel.name, "ok": ok, "reports": reports},
                                                            indent=2), encoding="utf-8")
    for r in reports:
        failed = [k for k, v in r["checks"].items() if not v]
        print(f"python {r.get('python', r['python_request'])}: {'PASS' if not failed else 'FAIL ' + ', '.join(failed)}"
              f" ({r.get('integration_summary', '')})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
