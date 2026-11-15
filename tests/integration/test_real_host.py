"""Real Core host integration tests (G3 handshake/lifecycle, G4 faults, G7 SDK client).

Requires ``NATIVEHTMLKIT_HOST_BINARY`` (an exact prebuilt host; never built here).
Without it every test is SKIPPED and the qualification runner reports BLOCKED.
Default mode is the host's documented ``--headless`` test mode; ``NHK_IT_DESKTOP=1``
runs the same scenarios with real windows on the current desktop session.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[1] / "src"
INSTALLED = os.environ.get("NATIVEHTMLKIT_TEST_INSTALLED") == "1"
HOST = os.environ.get("NATIVEHTMLKIT_HOST_BINARY")
EXPORT_HOST = bool(HOST)  # installed mode without an override must use the wheel's bundled host
if not HOST and INSTALLED:
    from nativehtmlkit.launcher import bundled_host_path
    HOST = str(bundled_host_path()) if bundled_host_path().is_file() else None
DESKTOP = os.environ.get("NHK_IT_DESKTOP") == "1"
pytestmark = pytest.mark.skipif(not HOST, reason="BLOCKED: no host (set NATIVEHTMLKIT_HOST_BINARY)")


@dataclass
class Run:
    rc: int | None
    stdout: str
    stderr: str
    records: list
    seconds: float
    leftovers: list
    session: str
    host_log: Path
    diag_dir: Path
    timed_out: bool = False
    checks: dict = field(default_factory=dict)

    def failed(self):
        return {k: v for k, v in self.checks.items() if v["status"] != "pass"}

    def info(self, name):
        return [r for r in self.records if r.get("kind") == "info" and r.get("name") == name]


def _marker_processes(marker: str, host: str) -> list:
    """Processes still alive from this run (Linux: env marker; Windows: command line / host path)."""
    found = []
    if sys.platform.startswith("linux"):
        needle = f"NHK_IT_MARKER={marker}".encode()
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit() or int(entry.name) == os.getpid():
                continue
            try:
                if needle in (entry / "environ").read_bytes().split(b"\0"):
                    found.append({"pid": int(entry.name), "exe": os.path.basename(os.readlink(entry / "exe"))})
            except OSError:
                continue
    elif os.name == "nt":
        script = ("Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.ParentProcessId -ne $PID } | Where-Object { $_.CommandLine -like '*%s*' -or "
                  "$_.ExecutablePath -eq '%s' } | ForEach-Object { \"$($_.ProcessId) $($_.Name)\" }") % (marker, host)
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=60)
        for line in out.stdout.splitlines():
            if line.strip():
                pid, name = line.split(" ", 1)
                if int(pid) != os.getpid():
                    found.append({"pid": int(pid), "exe": name})
    return found


def launch(entry: str, tmp_path: Path, *, env: dict | None = None, timeout: float = 120,
           diagnostics: str | None = None, command: list | None = None, signal_after: float | None = None,
           signal_on_ready: bool = False, signal_on_host_log: str | None = None) -> Run:
    marker = uuid.uuid4().hex[:12]
    session = f"it:{marker}.s"
    out = tmp_path / "records.jsonl"
    diag = tmp_path / "diag"
    host_log = tmp_path / "host-stderr.jsonl"
    environment = os.environ.copy()
    for key in [k for k in environment if k.startswith("UI4ME_")]:
        environment.pop(key)
    environment.update({
        "NHK_IT_OUT": str(out), "NHK_IT_MARKER": marker, "NHK_IT_EXPECT_SESSION": session,
        "NATIVEHTMLKIT_DIAGNOSTIC_SESSION_ID": session, "NATIVEHTMLKIT_DIAGNOSTICS_DIR": str(diag),
        "NATIVEHTMLKIT_HOST_LOG": str(host_log),
        "PYTHONPATH": os.pathsep.join(([] if INSTALLED else [str(SRC)]) + [str(HERE)]),
    })
    if EXPORT_HOST:
        environment["NATIVEHTMLKIT_HOST_BINARY"] = HOST
    else:
        environment.pop("NATIVEHTMLKIT_HOST_BINARY", None)
    if diagnostics:
        environment["NATIVEHTMLKIT_DIAGNOSTICS"] = diagnostics
    else:
        environment.pop("NATIVEHTMLKIT_DIAGNOSTICS", None)
    if not DESKTOP:
        environment["NATIVEHTMLKIT_TEST_MODE"] = "1"
    environment.update(env or {})
    argv = command or [sys.executable, "-m", "nativehtmlkit", "run", f"it_apps:{entry}", "--name", f"IT {entry} {marker}"]
    started = time.monotonic()
    options = {"start_new_session": True} if os.name == "posix" else {"creationflags": 0x00000200}
    proc = subprocess.Popen(argv, cwd=tmp_path, env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            **options)
    timed_out = False
    try:
        if signal_on_host_log is not None:
            # A desktop host keeps its failure window open for the user after a backend crash;
            # stop the launcher once the expected output was relayed (seen in the raw host log).
            seen_by = time.monotonic() + timeout / 2
            while time.monotonic() < seen_by and proc.poll() is None:
                if host_log.exists() and signal_on_host_log in host_log.read_text(encoding="utf-8", errors="replace"):
                    time.sleep(0.5)
                    break
                time.sleep(0.05)
            if proc.poll() is None:
                if os.name == "posix":
                    proc.send_signal(signal.SIGTERM)
                else:
                    proc.kill()  # the launcher's kill-on-close job ends host and backend (leftovers checked)
        elif signal_on_ready:
            # Deterministic: signal once the backend's app.ready completed (trace record),
            # instead of a fixed sleep that races a slow start.
            ready_by = time.monotonic() + timeout / 2
            while time.monotonic() < ready_by and proc.poll() is None and not _ready_recorded(diag):
                time.sleep(0.05)
            proc.send_signal(signal.SIGTERM if os.name == "posix" else signal.CTRL_BREAK_EVENT)
        elif signal_after is not None:
            time.sleep(signal_after)
            proc.send_signal(signal.SIGTERM if os.name == "posix" else signal.CTRL_BREAK_EVENT)
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "posix":
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
        stdout, stderr = proc.communicate()
    seconds = time.monotonic() - started
    leftovers = []
    for _ in range(50):  # allow 5 s for supervised children to finish exiting
        leftovers = _marker_processes(marker, HOST)
        if not leftovers:
            break
        time.sleep(0.1)
    records = []
    if out.exists():
        records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    run = Run(proc.returncode, stdout.decode("utf-8", "replace"), stderr.decode("utf-8", "replace"), records,
              seconds, leftovers, session, host_log, diag, timed_out)
    for record in records:
        if record.get("kind") == "check":
            previous = run.checks.get(record["name"])
            if previous is None or previous["status"] == "pass":
                run.checks[record["name"]] = record
    (tmp_path / "run-summary.json").write_text(json.dumps({
        "entry": entry, "rc": run.rc, "seconds": round(seconds, 3), "timed_out": timed_out,
        "leftovers": leftovers, "failed": run.failed(), "checks": len(run.checks)}, indent=2, default=repr))
    (tmp_path / "launcher-stderr.txt").write_text(run.stderr, encoding="utf-8")
    return run


def _ready_recorded(diag: Path) -> bool:
    for file in diag.glob("python-*.jsonl") if diag.exists() else []:
        for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if record.get("event") == "rpc.completed" and record["context"].get("method") == "app.ready":
                return True
    return False


def assert_clean(run: Run, *, rc=0):
    assert not run.timed_out, f"timed out after {run.seconds:.1f}s\n{run.stderr[-3000:]}"
    if rc is not None:
        assert run.rc == rc, f"exit {run.rc}\n{run.stderr[-3000:]}"
    assert not run.leftovers, f"orphaned processes: {run.leftovers}"
    assert not run.failed(), json.dumps(run.failed(), indent=1, ensure_ascii=False)[:4000]


def require(run: Run, *names):
    missing = [n for n in names if n not in run.checks]
    assert not missing, f"scenario did not reach checks {missing}\n{run.stderr[-3000:]}"


def host_records(run: Run) -> list:
    if not run.host_log.exists():
        return []
    result = []
    for line in run.host_log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            result.append(json.loads(line))
        except ValueError:
            pass
    return result


def sdk_records(run: Run) -> list:
    result = []
    for file in sorted(run.diag_dir.glob("python-*.jsonl")) if run.diag_dir.exists() else []:
        result += [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]
    return result


def test_api_operations_against_real_host(tmp_path):
    run = launch("api_main", tmp_path)
    require(run, "hello.protocol_v1", "startup.open_html_failure_catchable",
            "startup.early_secondary_close_gets_closed_event", "startup.app_still_running",
            "bitmap.transport_file_released", "bitmap.host_budget_refused_with_busy", "env.wire_vars_scrubbed", "env.child_inherits_no_wire_vars",
            "session.flows_to_backend", "document.unicode_value_roundtrip", "forms.form_data",
            "forms.submit_event_delivered", "callback.not_on_reader_thread", "subscription.disposed_sync",
            "nodes.query_nodes", "bitmap.present", "resources.register", "window.set_get", "lowlevel.host_diagnostics",
            "lowlevel.unknown_method_code", "lowlevel.unknown_member_code", "limits.oversize_html_code",
            "limits.frame_over_2mib_refused_locally", "deadline.outcome_unknown", "deadline.session_usable_after",
            "stale.local_rejection", "stale.host_code_closed", "rapid.windows_released",
            "multi.events_routed_per_document")
    assert run.info("on_shutdown_ran"), run.stderr[-2000:]
    assert_clean(run)


def test_asyncio_adapter_against_real_host(tmp_path):
    run = launch("async_main", tmp_path)
    require(run, "async.gather_60_rpcs", "async.loop_progress_during_rpcs", "async.ordered_fifo_callbacks",
            "async.callback_on_loop_thread", "async.loop_progress_while_callback_awaits", "async.sync_thread_mixing",
            "async.subscription_disposed", "async.deadline_outcome_unknown", "async.usable_after_deadline",
            "async.usable_after_cancel", "async.no_blocking_call_on_loop", "async.run_returned_after_shutdown",
            "async.dispatcher_stopped")
    assert_clean(run)


def test_slow_and_throwing_callbacks_then_quit_is_bounded(tmp_path):
    run = launch("callbacks_main", tmp_path)
    require(run, "callbacks.slow_running_before_quit")
    assert "intentional failure in callback" in run.stderr  # reported, not swallowed
    shutdown = run.info("on_shutdown_ran")
    assert shutdown and shutdown[0]["seconds"] < 12, shutdown
    assert run.seconds < 30
    assert_clean(run)


def test_host_killed_mid_request_no_orphans(tmp_path):
    run = launch("kill_host_main", tmp_path, timeout=60)
    assert not run.timed_out and run.seconds < 30
    assert run.rc not in (0, None), "a killed host must not look like success"
    assert run.info("killing_host"), run.stderr[-2000:]
    outcome = run.info("kill_outcome")
    if outcome:  # the backend usually dies with the host before it can report
        assert outcome[0]["other"] == 0 and outcome[0]["seconds"] < 11
    (tmp_path / "observation.json").write_text(json.dumps({"backend_reported": bool(outcome),
                                                           "outcome": outcome, "rc": run.rc}))
    assert not run.leftovers, run.leftovers


@pytest.mark.skipif(DESKTOP, reason="BLOCKED in desktop mode: after a protocol violation the desktop host keeps its "
                    "failure window open for the user (no unattended exit); covered headless")
def test_malformed_frame_from_sdk_ends_session_causally(tmp_path):
    run = launch("malformed_main", tmp_path, timeout=60)
    assert not run.timed_out and run.seconds < 30
    assert run.rc != 0, "a protocol violation must not end with success"
    if "malformed.pending_failed_with_disconnect" in run.checks:
        assert not run.failed(), run.failed()
    assert not run.leftovers, run.leftovers


SENTINEL = "nhkSENTINEL" + "7f3a9c21"


@pytest.mark.parametrize("level", ["normal", "trace"])
@pytest.mark.parametrize("bug", [False, True])
def test_submit_did_nothing_diagnostics(tmp_path, level, bug):
    zip_path = tmp_path / "support.zip"
    run = launch("submit_main", tmp_path, diagnostics=level,
                 env={"NHK_IT_SUBMIT_BUG": "1" if bug else "0", "NHK_IT_SENTINEL": SENTINEL, "NHK_IT_ZIP": str(zip_path)})
    require(run, "submit.bug_reproduced_handler_not_run" if bug else "submit.handler_ran")
    assert_clean(run)
    sdk = sdk_records(run)
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as archive:
        names = set(archive.namelist())
        blob = b"".join(archive.read(n) for n in names)
        manifest = json.loads(archive.read("manifest.json"))
    assert names == {"manifest.json", "timeline.jsonl"}
    assert SENTINEL.encode() not in blob
    assert SENTINEL not in json.dumps(sdk)
    assert manifest["session_id"] == run.session
    hosts = host_records(run)
    sentinel_in_host_log = SENTINEL in run.host_log.read_text(encoding="utf-8", errors="replace")
    (tmp_path / "privacy.json").write_text(json.dumps({"level": level, "bug": bug, "sdk_records": len(sdk),
                                                       "host_records": len(hosts),
                                                       "sentinel_in_raw_host_log": sentinel_in_host_log}))
    # The typed/set sentinel must not reach the host's stderr either (Core redacts backend
    # output tokens and logs metadata only).
    assert not sentinel_in_host_log, "sentinel found in raw host stderr"
    if level == "normal":
        assert sdk == []  # nothing persisted at normal level
        return
    events = [r["event"] for r in sdk]
    assert all(r["session_id"] == run.session for r in sdk)
    notification = [r for r in sdk if r["event"] == "host.notification" and r["context"].get("event_type") == "submit"]
    assert notification, events
    seq = notification[0]["context"]["event_seq"]
    dispatch = [r for r in sdk if r["event"] == "document.dispatch" and r["context"].get("event_type") == "submit"]
    assert dispatch and dispatch[0]["context"]["handlers"] == 1
    if bug:
        # The record that pinpoints the stall: the event arrived, no handler matched.
        assert dispatch[0]["context"]["matched"] == 0
        assert not [r for r in sdk if r["event"] == "rpc.started" and r["context"].get("cause_seq") == seq
                    and r["context"].get("op") == "set_text"]
    else:
        assert dispatch[0]["context"]["matched"] == 1
        caused = [r for r in sdk if r["event"] == "rpc.started" and r["context"].get("cause_seq") == seq]
        ops = [r["context"].get("op") for r in caused]
        assert ops == ["get_value", "set_text"], ops  # callback read the form, then mutated the UI
        completed = {r["context"]["request_id"] for r in sdk if r["event"] == "rpc.completed"}
        assert all(r["context"]["request_id"] in completed for r in caused)
        assert [r for r in sdk if r["event"] == "callback.completed" and r["context"].get("event_seq") == seq]
        # Cross-process: the host saw and answered exactly these SDK request ids (Core >= 1.0.2 trace).
        host_events = [r.get("fields", {}) for r in hosts]
        for request in caused:
            rid = request["context"]["request_id"]
            for kind in ("rpc.received", "rpc.completed"):
                assert [f for f in host_events if f.get("event") == kind and f.get("id") == rid
                        and f.get("method") == "document.command"], (kind, rid)
    note = notification[0]["context"]  # the host recorded sending the very event the SDK received
    sent = [f for f in (r.get("fields", {}) for r in hosts) if f.get("event") == "notify.sent"
            and f.get("type") == "submit"]
    assert [f for f in sent if f.get("window_id") == note["window_id"] and f.get("document_id") == note["document_id"]], sent
    timeline = [json.loads(l) for l in zipfile.ZipFile(zip_path).read("timeline.jsonl").decode().splitlines()]
    assert {r["event"] for r in timeline} >= {"host.notification", "document.dispatch", "rpc.started"}


def test_session_id_reaches_host_records(tmp_path):
    """NATIVEHTMLKIT_DIAGNOSTIC_SESSION_ID set by the launcher tags every host record (Core >= 1.0.2)."""
    run = launch("submit_main", tmp_path, diagnostics="debug", env={"NHK_IT_SENTINEL": SENTINEL})
    assert_clean(run)
    hosts = host_records(run)
    assert hosts, "no host records captured"
    sessions = {r.get("diagnostic_session_id") for r in hosts}
    assert sessions == {run.session}, f"host records carry {sessions}, launcher session {run.session}"
    backend = [r for r in sdk_records(run)]
    assert backend and {r["session_id"] for r in backend} == {run.session}


@pytest.mark.parametrize("level", ["off", "normal", "debug", "trace"])
@pytest.mark.parametrize("mode", ["direct", "runner"])
def test_backend_output_and_traceback_survive_every_level(tmp_path, level, mode):
    """FR-PY-01 / NHK-CROSS-0007: Core relays backend output through its log filter; the SDK
    launcher keeps the host at >= normal so prints and tracebacks are never lost (even at off)."""
    if mode == "direct":
        command = [sys.executable, str(HERE / "crash_app.py")]
    else:
        command = [sys.executable, "-m", "nativehtmlkit", "--diagnostics", level, "run", "crash_app:main",
                   "--name", "IT crash runner"]
    run = launch("crash", tmp_path, diagnostics=level, command=command, timeout=60,
                 signal_on_host_log="backend crashed here" if DESKTOP else None)
    assert not run.timed_out and run.rc not in (0, None), (run.rc, run.stderr[-1500:])
    assert "STDOUT-LINE from backend" in run.stdout, run.stdout[-500:]
    assert "STDERR-LINE from backend" in run.stderr
    assert "Traceback" in run.stderr and "RuntimeError: backend crashed here" in run.stderr, run.stderr[-1500:]
    assert not run.leftovers, run.leftovers
    if level == "off":
        assert sdk_records(run) == []  # the SDK's own records stay off


def test_diagnostic_overflow_is_disclosed(tmp_path):
    zip_path = tmp_path / "support.zip"
    run = launch("overflow_main", tmp_path, diagnostics="trace", env={"NHK_IT_ZIP": str(zip_path)})
    require(run, "overflow.eviction_disclosed")
    assert_clean(run)
    manifest = json.loads(zipfile.ZipFile(zip_path).read("manifest.json"))
    assert manifest["exporter"]["history_evicted"] > 0
    assert "dropped" in manifest["exporter"]


def test_direct_start_two_process_bootstrap(tmp_path):
    script = HERE / "direct_start_app.py"
    run = launch("direct", tmp_path, command=[sys.executable, str(script)])
    require(run, "direct.connected", "env.wire_vars_scrubbed")
    roles = [r["role"] for r in run.records if r.get("kind") == "toplevel"]
    assert sorted(roles) == ["backend", "launcher"], roles  # documented: top-level code runs twice
    assert_clean(run)


ARGV_CASES = ["a b", 'q"uote', "back\\slash\\", "", "--flag=1", "ü😀", "$HOME `id` ;&|", "tab\there",
              "new\nline", "'single'", "%PATH%", "del\x7fchar", "ctl\x01"]


def test_direct_start_arguments_round_trip(tmp_path):
    """FR-PY-08: user arguments reach the backend byte-exact (DEL escaped for TOML)."""
    run = launch("direct", tmp_path, command=[sys.executable, str(HERE / "direct_start_app.py"), *ARGV_CASES])
    assert_clean(run)
    backend = [r for r in run.records if r.get("kind") == "toplevel" and r["role"] == "backend"]
    assert backend and backend[0]["argv"] == ARGV_CASES, backend


def test_direct_start_refuses_host_placeholder_argument(tmp_path):
    run = launch("direct", tmp_path, command=[sys.executable, str(HERE / "direct_start_app.py"), "{app_dir}"])
    assert run.rc != 0, run.rc
    assert "StartupError" in run.stderr and "{app_dir}" in run.stderr, run.stderr[-1000:]
    assert not [r for r in run.records if r.get("kind") == "toplevel" and r["role"] == "backend"]
    assert not run.leftovers


def test_scaffolded_app_starts_and_stops_on_sigterm(tmp_path):
    if os.name != "posix":
        pytest.skip("SIGTERM relay is POSIX; Windows uses the job object (covered by the GUI suite)")
    project = tmp_path / "hello-app"
    scaffold_env = dict(os.environ)
    if not INSTALLED:
        scaffold_env["PYTHONPATH"] = str(SRC)
    # A unique name gives a unique app id (the scaffold uses instance="single"), so parallel
    # suites never hand their launch to another suite's running instance.
    unique = "IT Scaffold " + uuid.uuid4().hex[:8]
    subprocess.run([sys.executable, "-m", "nativehtmlkit.scaffold", str(project), "--name", unique],
                   check=True, capture_output=True, env=scaffold_env)
    run = launch("scaffold", tmp_path, command=[sys.executable, str(project / "app.py")], diagnostics="trace",
                 signal_on_ready=True, timeout=40)
    assert not run.timed_out
    assert _ready_recorded(run.diag_dir), "app never reached app.ready"
    assert run.rc == 128 + signal.SIGTERM, (run.rc, run.stderr[-2000:])
    assert "Traceback" not in run.stderr, run.stderr[-2000:]
    hosts = host_records(run)
    assert hosts, "host produced no records"
    assert not run.leftovers, run.leftovers


def test_version_and_doctor_report_real_host(tmp_path):
    env = dict(os.environ)
    if EXPORT_HOST:
        env["NATIVEHTMLKIT_HOST_BINARY"] = HOST
    if not INSTALLED:
        env["PYTHONPATH"] = str(SRC)
    out = subprocess.run([sys.executable, "-m", "nativehtmlkit", "version"], capture_output=True, text=True, env=env,
                         timeout=60)
    assert out.returncode == 0, out.stderr
    info = json.loads(out.stdout)
    assert info["protocol_version"] == 1
    assert info["host"]["source"] == ("environment" if EXPORT_HOST else "bundled")
    assert len(info["host"]["sha256"]) == 64
    if not EXPORT_HOST:
        assert info["host"]["manifest_match"] is True
    doctor = subprocess.run([sys.executable, "-m", "nativehtmlkit", "doctor"], capture_output=True, text=True,
                            env=env, timeout=60)
    assert doctor.returncode == 0, doctor.stderr
    assert doctor.stdout.strip()
