"""NativeHTMLKit SDK developer tools. `run` avoids double-running module setup."""
from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from . import diagnostics
from . import _bootstrap
from .application import Application
from .launcher import host_binary, host_info

DOCTOR_TIMEOUT_S = 15.0

def _resolve(spec: str):
    if ":" not in spec:
        raise ValueError("entry point must be MODULE:CALLABLE")
    module, attr = spec.split(":", 1)
    if not module or not attr or attr.startswith("_") or any(not part.isidentifier() for part in (module.split(".") + attr.split("."))):
        raise ValueError("invalid entry point; use e.g. demo.app:main")
    current = importlib.import_module(module)
    for part in attr.split("."):
        current = getattr(current, part)
    if not callable(current):
        raise TypeError("entry point is not callable")
    return current


def run(spec: str, *, name: str) -> int:
    # Host invokes this exact module on a second process. Only imports the app
    # module in that managed backend, never in the developer's launcher.
    if _bootstrap.managed():
        # Connect first: this consumes and scrubs the launch credential BEFORE any code of the
        # application's entry module runs (its import-time code must not see UI4ME_TOKEN).
        with Application.from_environment() as app:
            _bootstrap.forget_host_environment()
            callback = _resolve(spec)
            result = callback(app)
            if inspect.isawaitable(result):
                # A setup coroutine is allowed; use an explicitly async app runner
                # for background tasks that must live beyond setup.
                import asyncio
                asyncio.run(result)
            app.run()
        return 0
    binary = host_binary()
    with tempfile.TemporaryDirectory(prefix="nativehtmlkit-entry-") as folder:
        target = Path(folder)
        manifest = _bootstrap.write_manifest(
            target, program=sys.executable,
            arguments=["-m", "nativehtmlkit", "run", spec, "--name", name],
            cwd=os.getcwd(), app_id=_bootstrap.default_app_id(spec, name),
            name=name, version=None, icon=None, instance="multiple",
            startup_timeout_ms=30000, shutdown_timeout_ms=5000,
            max_windows=16, env={"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
        )
        args = [str(binary), "run", "--app", str(manifest)]
        if os.environ.get("NATIVEHTMLKIT_TEST_MODE") == "1":
            args.append("--headless")
        return _bootstrap.run_host(args, env=os.environ.copy())


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="nativehtmlkit-python", description=__doc__)
    parser.add_argument("--diagnostics", choices=("off", "normal", "debug", "trace"),
                        help="Diagnostic detail level for this SDK process, the host and the backend")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("run", help="Run a MODULE:CALLABLE in a managed native backend")
    p.add_argument("entrypoint")
    p.add_argument("--name", default="NativeHTMLKit App")
    p.add_argument("--host-log", type=Path, help="SENSITIVE: append raw host stderr records to this file (0600)")
    commands.add_parser("doctor", help="Run the host's own environment report")
    commands.add_parser("version", help="Print SDK/protocol versions and host provenance as JSON")
    support = commands.add_parser("support", help="Export a redacted local support bundle (explicit, local only)")
    support.add_argument("output", type=Path)
    support.add_argument("--session", help="Diagnostics session ID (default: the most recently recorded one)")
    support.add_argument("--force", action="store_true", help="replace an existing output file")
    args = parser.parse_args(argv)
    if args.diagnostics:
        os.environ["NATIVEHTMLKIT_DIAGNOSTICS"] = args.diagnostics
        if args.diagnostics == "trace":
            os.environ["NATIVEHTMLKIT_VERBOSE"] = "1"
    try:
        if args.command == "run":
            if args.host_log:
                os.environ["NATIVEHTMLKIT_HOST_LOG"] = str(args.host_log.expanduser().resolve())
            return run(args.entrypoint, name=args.name)
        if args.command == "doctor":
            binary = host_binary()
            try:
                return subprocess.run([str(binary), "doctor"], timeout=DOCTOR_TIMEOUT_S, check=False).returncode
            except subprocess.TimeoutExpired:
                raise TimeoutError(f"host doctor did not finish within {DOCTOR_TIMEOUT_S:g} s") from None
        if args.command == "version":
            from . import __version__
            from .client import CLIENT_VERSION
            info = {"sdk_version": __version__, "client_version": CLIENT_VERSION, "protocol_version": 1,
                    "python": sys.version.split()[0], "host": host_info()}
            print(json.dumps(info, indent=2, sort_keys=True))
            host = info["host"]
            return 0 if host.get("path") and host.get("manifest_match") is not False else 1
        if args.command == "support":
            session = args.session or diagnostics.latest_session() or diagnostics.SESSION_ID
            print(diagnostics.export_bundle(args.output, capture_environment=True, session=session,
                                            overwrite=args.force))
            return 0
    except (OSError, ValueError, TypeError, ImportError, TimeoutError) as exc:
        diagnostics.record("cli.failed", level="ERROR", exception_type=type(exc).__name__)
        print(f"nativehtmlkit: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
