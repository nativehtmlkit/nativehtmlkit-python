"""Reproducing tests for the independent final adversarial review (FR-PY-01..18).

Ported from verification/2026-11-15-sdk/final-review/python-evidence/*.py. Fake hosts use
the independent framing oracle in tests/oracle.py, never the SDK's own framing code.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import socket
import stat
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

import oracle
from nativehtmlkit import diagnostics
from nativehtmlkit.application import Application, Document, Window
from nativehtmlkit.client import RpcClient, SocketStream, MAX_FRAME_BYTES

ROOT = Path(__file__).resolve().parents[1]


class Host:
    def __init__(self, **kwargs):
        a, b = socket.socketpair()
        self.sock = b
        self.client = RpcClient(SocketStream(a), **kwargs)

    def recv(self, timeout=5):
        return oracle.recv(self.sock, timeout)

    def send(self, message):
        oracle.send(self.sock, {"jsonrpc": "2.0", **message})

    def close(self):
        self.client.close()
        self.sock.close()


@pytest.fixture
def host():
    h = Host(ordered_notifications=True)
    yield h
    h.close()


# ---------------------------------------------------------------- FR-PY-02
def test_fr02_public_future_callbacks_never_run_on_reader(host):
    """e1.py: a done-callback on a call_async future ran on the reader thread and deadlocked a nested RPC."""
    seen = {}
    future = host.client.call_async("dialog.open_files", {"window_id": "w1"})

    def done(_f):
        seen["thread"] = threading.current_thread().name
        try:
            seen["nested"] = host.client.call("window.get", {"window_id": "w1"}, timeout=2)
        except Exception as error:  # pragma: no cover - the failure mode under test
            seen["nested"] = type(error).__name__
    future.add_done_callback(done)
    request = host.recv()
    host.send({"id": request["id"], "result": {"paths": []}})
    nested = host.recv()
    host.send({"id": nested["id"], "result": {"window_id": "w1"}})
    deadline = time.monotonic() + 3
    while "nested" not in seen and time.monotonic() < deadline:
        time.sleep(0.01)
    assert seen.get("nested") == {"window_id": "w1"}, seen
    assert "receiver" not in seen["thread"] and "writer" not in seen["thread"]


def test_fr02_cancelling_public_future_sends_request_cancel(host):
    future = host.client.call_async("dialog.open_files", {"window_id": "w1"})
    request = host.recv()
    assert future.cancel()
    cancel = host.recv()
    assert cancel["method"] == "request.cancel" and cancel["params"] == {"id": request["id"]}
    assert future.request_id == request["id"]


def test_fr02_wait_false_dialog_future_completes_off_reader(host):
    app = Application(host.client)
    window = Window(app, "w1")
    app._windows["w1"] = window
    future = window.open_files(wait=False)
    threads = []
    future.add_done_callback(lambda f: threads.append(threading.current_thread().name))
    request = host.recv()
    host.send({"id": request["id"], "result": {"cancelled": True, "paths": []}})
    assert future.result(3) == {"cancelled": True, "paths": []}
    deadline = time.monotonic() + 2
    while not threads and time.monotonic() < deadline:
        time.sleep(0.01)
    assert threads and "receiver" not in threads[0]


# ---------------------------------------------------------------- FR-PY-03
@pytest.mark.parametrize("kind", [SystemExit, KeyboardInterrupt, ValueError])
def test_fr03_host_request_always_answered_without_exception_text(kind):
    """e2.py: SystemExit/KeyboardInterrupt in a before_close handler left the host unanswered."""
    h = Host()
    try:
        def handler(_params):
            raise kind("secret-message /home/u/file.txt")
        h.client.on_request("window.before_close", handler)
        h.send({"id": "h1", "method": "window.before_close", "params": {"window_id": "w1"}})
        reply = h.recv(timeout=3)
        assert reply["id"] == "h1" and reply["error"]["code"] == -32603
        assert "secret-message" not in json.dumps(reply)  # M17: no exception text to the host
        if kind is not ValueError:
            # Controlled effect: the SDK asks the host for an orderly quit.
            follow = h.recv(timeout=3)
            assert follow["method"] == "app.request_quit"
    finally:
        h.close()


# ---------------------------------------------------------------- FR-PY-04
@pytest.mark.parametrize("use_run", [False, True])
def test_fr04_async_close_inside_handler_does_not_hang(use_run):
    """e8.py: `await aapp.close()` inside a dispatched async handler never returned."""
    h = Host(ordered_notifications=True)
    stop = threading.Event()

    def serve():
        try:
            while not stop.is_set():
                message = h.recv(20)
                if "id" in message and "method" in message:
                    result = {"window_id": "w1"} if message["method"] == "window.create" else \
                        {"document_id": "d1"} if message["method"] == "document.load" else {}
                    h.send({"id": message["id"], "result": result})
                    if message["method"] == "app.ready":
                        h.send({"method": "document.event", "params": {"window_id": "w1", "document_id": "d1",
                                "event": {"type": "click", "element": "quit"}}})
        except Exception:
            pass
    threading.Thread(target=serve, daemon=True).start()

    async def scenario():
        app = Application(h.client)
        aapp = app.async_adapter()
        window = await asyncio.to_thread(app.open_html, "<button id=quit>")
        done = asyncio.Event()

        async def on_quit(_event):
            await aapp.close()
            done.set()
        aapp.on_document_event(window.document, "click", on_quit, element="quit")
        if use_run:
            runner = asyncio.create_task(aapp.run())
        else:
            await asyncio.to_thread(app.ready)
        await asyncio.wait_for(done.wait(), 5)
        if use_run:
            await asyncio.wait_for(runner, 5)
        await asyncio.wait_for(aapp.dispatcher._task, 5)
    try:
        asyncio.run(asyncio.wait_for(scenario(), 15))
    finally:
        stop.set()
        h.close()


# ---------------------------------------------------------------- FR-PY-05 / 06
def _fake_install(tmp_path, *, manifest=True, sha=None):
    from nativehtmlkit import launcher
    folder = tmp_path / "_bin"
    folder.mkdir()
    host = folder / launcher.HOST_NAME
    host.write_bytes(b"\x7fELF genuine host bytes")
    if manifest:
        digest = sha or hashlib.sha256(host.read_bytes()).hexdigest()
        (folder / "HOST-MANIFEST.json").write_text(json.dumps({"host_sha256": digest, "host_file": host.name,
                                                               "protocol_version": 1}))
    return host


def test_fr05_tampered_bundled_host_is_refused(tmp_path, monkeypatch):
    from nativehtmlkit import launcher
    from nativehtmlkit.errors import HostVerificationError
    host = _fake_install(tmp_path)
    monkeypatch.setattr(launcher, "bundled_host_path", lambda: host)
    for name in ("NATIVEHTMLKIT_HOST_BINARY", "UI4ME_HOST_BINARY", "NATIVEHTMLKIT_ALLOW_PATH_HOST"):
        monkeypatch.delenv(name, raising=False)
    assert launcher.host_binary() == host  # genuine: accepted
    host.write_bytes(b"#!/bin/sh\necho TAMPERED\n")
    with pytest.raises(HostVerificationError):
        launcher.host_binary()


def test_fr05_bundled_host_without_manifest_is_refused(tmp_path, monkeypatch):
    from nativehtmlkit import launcher
    from nativehtmlkit.errors import HostVerificationError
    host = _fake_install(tmp_path, manifest=False)
    monkeypatch.setattr(launcher, "bundled_host_path", lambda: host)
    monkeypatch.delenv("NATIVEHTMLKIT_HOST_BINARY", raising=False)
    with pytest.raises(HostVerificationError):
        launcher.host_binary()


@pytest.mark.parametrize("entry", ["doctor", "run"])
def test_fr05_every_launch_path_verifies(tmp_path, monkeypatch, entry):
    from nativehtmlkit import launcher, __main__ as cli
    host = _fake_install(tmp_path, sha="0" * 64)  # manifest pins another binary
    monkeypatch.setattr(launcher, "bundled_host_path", lambda: host)
    monkeypatch.setattr(cli, "host_binary", launcher.host_binary)
    monkeypatch.delenv("NATIVEHTMLKIT_HOST_BINARY", raising=False)
    calls = []
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(cli._bootstrap, "run_host", lambda *a, **k: calls.append(a) or 0)
    argv = ["doctor"] if entry == "doctor" else ["run", "x.y:main"]
    assert cli.main(argv) == 1
    assert calls == []  # never executed


def test_fr05_application_start_and_host_wrapper_verify(tmp_path, monkeypatch):
    from nativehtmlkit import launcher, _bootstrap
    host = _fake_install(tmp_path, sha="0" * 64)
    monkeypatch.setattr(launcher, "bundled_host_path", lambda: host)
    monkeypatch.delenv("NATIVEHTMLKIT_HOST_BINARY", raising=False)
    monkeypatch.setattr(sys, "argv", ["nativehtmlkit-python-host", "--version"])
    executed = []
    monkeypatch.setattr(launcher.os, "execv", lambda *a: executed.append(a))
    monkeypatch.setattr(launcher.subprocess, "call", lambda *a, **k: executed.append(a))
    assert launcher.main() == 1 and executed == []
    monkeypatch.setattr(_bootstrap, "backend_command", lambda: (sys.executable, ["app.py"], "id", "label"))
    with pytest.raises(_bootstrap.StartupError):
        _bootstrap.launch(name="x", app_id=None, version=None, icon=None, instance="multiple",
                          startup_timeout_ms=30000, shutdown_timeout_ms=5000, max_windows=4)


def test_fr06_path_host_requires_opt_in_and_never_uses_cwd(tmp_path, monkeypatch, capsys):
    from nativehtmlkit import launcher
    monkeypatch.setattr(launcher, "bundled_host_path", lambda: tmp_path / "missing" / launcher.HOST_NAME)
    monkeypatch.delenv("NATIVEHTMLKIT_HOST_BINARY", raising=False)
    monkeypatch.delenv("UI4ME_HOST_BINARY", raising=False)
    planted = tmp_path / launcher.HOST_NAME
    planted.write_bytes(b"#!/bin/sh\necho PLANTED\n")
    planted.chmod(0o755)
    elsewhere = tmp_path / "bin"
    elsewhere.mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join([".", "", str(elsewhere)]))
    monkeypatch.delenv("NATIVEHTMLKIT_ALLOW_PATH_HOST", raising=False)
    with pytest.raises(FileNotFoundError):
        launcher.host_binary()  # no implicit PATH fallback
    monkeypatch.setenv("NATIVEHTMLKIT_ALLOW_PATH_HOST", "1")
    with pytest.raises(FileNotFoundError):
        launcher.host_binary()  # "." / "" / cwd never searched, even when opted in
    real = elsewhere / launcher.HOST_NAME
    real.write_bytes(b"#!/bin/sh\n")
    real.chmod(0o755)
    found = launcher.host_binary()
    assert found.is_absolute() and found == real.resolve()
    assert "unpinned" in capsys.readouterr().err


# ---------------------------------------------------------------- FR-PY-08
def test_fr08_manifest_rejects_placeholder_and_escapes_del(tmp_path):
    from nativehtmlkit import _bootstrap
    path = _bootstrap.write_manifest(tmp_path, program=sys.executable, arguments=["app.py", "del\x7fchar"],
                                     cwd=str(tmp_path), app_id="a.b", name="n", version=None, icon=None,
                                     instance="multiple", startup_timeout_ms=30000, shutdown_timeout_ms=5000,
                                     max_windows=4, env={})
    text = path.read_text(encoding="utf-8")
    assert "\x7f" not in text and "\\u007f" in text
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        tomllib = pytest.importorskip("tomli")
    assert tomllib.loads(text)["backend"]["args"] == ["app.py", "del\x7fchar"]
    with pytest.raises(_bootstrap.StartupError, match="app_dir"):
        _bootstrap.write_manifest(tmp_path / "x", program=sys.executable, arguments=["{app_dir}"],
                                  cwd=str(tmp_path), app_id="a.b", name="n", version=None, icon=None,
                                  instance="multiple", startup_timeout_ms=30000, shutdown_timeout_ms=5000,
                                  max_windows=4, env={})


# ---------------------------------------------------------------- FR-PY-09
def test_fr09_sync_callback_raising_cancelled_error_keeps_dispatcher():
    """e4.py: a plain callback raising CancelledError ended the dispatcher task."""
    from nativehtmlkit.asyncio_api import EventDispatcher

    async def main():
        dispatcher = EventDispatcher()
        got = []

        def bad(_):
            raise asyncio.CancelledError()
        dispatcher.submit(bad, 1)
        dispatcher.submit(got.append, 2)
        for _ in range(100):
            if got:
                break
            await asyncio.sleep(0.01)
        alive = not dispatcher._task.done()
        await asyncio.wait_for(dispatcher.stop(), 2)
        return got, alive
    got, alive = asyncio.run(main())
    assert got == [2] and alive


# ---------------------------------------------------------------- FR-PY-10
def test_fr10_runner_scrubs_credentials_before_importing_entry(tmp_path, monkeypatch):
    from nativehtmlkit import __main__ as cli
    seen = {}
    (tmp_path / "tokmod.py").write_text(
        "import os\nIMPORT_SEES = 'UI4ME_TOKEN' in os.environ or 'UI4ME_ENDPOINT' in os.environ\n"
        "def main(app):\n    pass\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("UI4ME_ENDPOINT", "/nonexistent")
    monkeypatch.setenv("UI4ME_TOKEN", "ab" * 32)

    class FakeApp:
        def __enter__(self):
            seen["connected_env"] = "UI4ME_TOKEN" in os.environ
            return self

        def __exit__(self, *a):
            return False

        def run(self):
            pass

    def from_environment():
        os.environ.pop("UI4ME_TOKEN", None)
        os.environ.pop("UI4ME_ENDPOINT", None)
        return FakeApp()
    monkeypatch.setattr(cli.Application, "from_environment", staticmethod(from_environment))
    assert cli.run("tokmod:main", name="x") == 0
    import tokmod
    assert tokmod.IMPORT_SEES is False


# ---------------------------------------------------------------- FR-PY-11
@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits")
def test_fr11_support_zip_private_and_never_silently_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "umask", os.umask)  # no-op; use the real umask
    previous = os.umask(0o022)
    try:
        out = diagnostics.export_bundle(tmp_path / "support.zip", directory=tmp_path / "none")
        assert stat.S_IMODE(out.stat().st_mode) == 0o600
        with pytest.raises(FileExistsError):
            diagnostics.export_bundle(tmp_path / "support.zip", directory=tmp_path / "none")
        diagnostics.export_bundle(tmp_path / "support.zip", directory=tmp_path / "none", overwrite=True)
        assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    finally:
        os.umask(previous)


# ---------------------------------------------------------------- FR-PY-12 / M02
@pytest.mark.parametrize("params", [{"pad": "x" * MAX_FRAME_BYTES}, {"s": "\ud800"}, {"n": float("nan")},
                                    {"o": object()}, {1: "a", "1": "b"}, {"nested": {2: "x"}}])
def test_fr12_local_encode_errors_are_local_and_session_survives(host, params):
    from nativehtmlkit.errors import LocalRequestError, HostProtocolError
    with pytest.raises(LocalRequestError) as err:
        host.client.call_async("window.get", params)
    assert not isinstance(err.value, HostProtocolError)
    assert isinstance(err.value, ValueError)
    assert host.client._pending == {} and not host.client.closed
    assert oracle.recv_or_none(host.sock, 0.2) is None  # nothing was sent (outbound 2 MiB bound)
    future = host.client.call_async("window.list")
    request = host.recv()
    host.send({"id": request["id"], "result": []})
    assert future.result(3) == []


# ---------------------------------------------------------------- FR-PY-13
def test_fr13_error_hierarchy_and_classification():
    import nativehtmlkit as N
    from nativehtmlkit.client import ClientBusyError
    assert issubclass(N.StartupError, N.NativeHTMLKitError) and issubclass(N.StartupError, RuntimeError)
    error = N.RpcError(-32004, "closed")
    assert error.code == -32004 and error.classification == "NHK-HOST-RPC"
    assert ClientBusyError("x").classification == "NHK-CLIENT-BUSY"
    assert N.RpcTimeoutError("x").classification == N.RpcTimeoutError.code == "NHK-TRANSPORT-TIMEOUT"
    assert N.StartupError("x").classification == "NHK-STARTUP"


# ---------------------------------------------------------------- FR-PY-14
def test_fr14_unsubscribe_during_dispatch_is_honoured(host):
    app = Application(host.client)
    window = Window(app, "w1")
    app._windows["w1"] = window
    document = Document(window, "d1")
    window.document = document
    calls, done = [], threading.Event()

    def a(_):
        calls.append("a")
        unsubscribe_b()
        done.set()
    document.on("click", a)
    unsubscribe_b = document.on("click", lambda _: calls.append("b"))
    host.send({"method": "document.event", "params": {"window_id": "w1", "document_id": "d1",
               "event": {"type": "click"}}})
    assert done.wait(3)
    time.sleep(0.2)
    assert calls == ["a"]


def test_fr14_no_window_creation_after_shutdown(host):
    from nativehtmlkit.errors import ApplicationShutdownError
    app = Application(host.client)
    host.send({"method": "app.shutdown", "params": {"deadline_ms": 1000}})
    deadline = time.monotonic() + 3
    while not host.client.shutdown_requested.is_set() and time.monotonic() < deadline:
        time.sleep(0.01)
    with pytest.raises(ApplicationShutdownError):
        app.create_window()
    assert oracle.recv_or_none(host.sock, 0.2) is None


# ---------------------------------------------------------------- FR-PY-15
def test_fr15_diagnostic_method_and_op_are_allow_listed(host, monkeypatch, tmp_path):
    recorder = diagnostics.DiagnosticRecorder(level="trace", directory=tmp_path)
    monkeypatch.setattr(diagnostics, "_recorder", recorder)
    secret = "SENTINELVALUE_formsecret"
    host.client.call_async(secret, {})
    host.client.call_async("document.command", {"window_id": "w", "document_id": "d", "command": {"op": secret}})
    host.client.call_async("document.command", {"window_id": "w", "document_id": "d", "command": {"op": "set_text"}})
    host.send({"method": secret, "params": {}})
    time.sleep(0.3)
    blob = json.dumps(recorder.history())
    assert secret not in blob
    assert '"op": "set_text"' in blob and "unknown-method" in blob and "unknown-op" in blob


def test_fr15_embedded_contract_matches_pinned_snapshot():
    from nativehtmlkit import _contract
    matrix = json.loads((ROOT / "contracts/core-v1-method-matrix.json").read_text())
    assert set(_contract.METHODS) == set(matrix["methods"])
    assert set(_contract.DOCUMENT_OPS) == set(matrix["document_command_ops"])
    assert _contract.SOURCE_SHA256 == json.loads((ROOT / "contracts/SOURCE.json").read_text())["sha256"]


def test_fr17_redaction_is_key_based_for_messages():
    fields = diagnostics._safe({"error_message": "abc123", "title": "Invoice42", "label": "x"})
    assert set(fields.values()) == {"[REDACTED]"}


# ---------------------------------------------------------------- FR-PY-17 mutants
def test_m15_pending_table_empty_after_timeout_and_cancel(host):
    from nativehtmlkit.errors import RpcTimeoutError
    for _ in range(3):
        with pytest.raises(RpcTimeoutError):
            host.client.call("window.list", timeout=0.01)
    future = host.client.call_async("window.list")
    future.cancel()
    deadline = time.monotonic() + 2
    while (host.client._pending or host.client._request_meta) and time.monotonic() < deadline:
        time.sleep(0.01)
    assert host.client._pending == {} and host.client._request_meta == {}


def test_m20_direct_start_marker_refuses_second_host(monkeypatch):
    from nativehtmlkit import _bootstrap
    for name in ("UI4ME_ENDPOINT", "UI4ME_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("UI4ME_DIRECT_START", "1234")
    with pytest.raises(_bootstrap.StartupError, match="second native host"):
        _bootstrap.managed()


def test_oracle_and_sdk_framing_agree():
    """Independent oracle: SDK frames decode with the oracle and vice versa (unicode, sizes)."""
    from nativehtmlkit.client import encode_frame, read_frame, SocketStream as SDKStream
    a, b = socket.socketpair()
    try:
        for payload in ({"jsonrpc": "2.0", "id": "x", "result": "Příliš 😀"},
                        {"jsonrpc": "2.0", "method": "m", "params": {"s": "y" * 100_000}}):
            a.sendall(encode_frame(payload))
            assert oracle.recv(b) == payload
            oracle.send(b, payload)
            assert read_frame(SDKStream(a)) == payload
    finally:
        a.close()
        b.close()


# ---------------------------------------------------------------- FR-PY-18
def test_fr18_skill_marker_must_be_an_object(tmp_path):
    from nativehtmlkit import skills
    target = tmp_path / "nativehtmlkit-python"
    target.mkdir()
    (target / skills.MARKER).write_text("[]")
    with pytest.raises(ValueError):
        skills.skill_status(target)


# ---------------------------------------------------------------- re-review of the FR fixes (RR-1..4)
def test_rr1_systemexit_in_before_quit_allows_quit_without_loop():
    """review3/quitloop.py: a -32603 answer vetoed the quit and the follow-up request_quit looped."""
    h = Host()
    try:
        h.client.on_request("app.before_quit", lambda _p: sys.exit(0))
        h.client.on_request("window.before_close", lambda _p: sys.exit(0))
        h.send({"id": "q0", "method": "app.before_quit", "params": {"reason": "x"}})
        reply = h.recv()
        assert reply["id"] == "q0" and reply["result"] == {"allow": True}  # the user wants out: allow it
        h.send({"id": "c0", "method": "window.before_close", "params": {"window_id": "w1", "reason": "user"}})
        reply = h.recv()
        assert reply["id"] == "c0" and reply["error"]["code"] == -32603
        quit_request = h.recv()
        assert quit_request["method"] == "app.request_quit"
        h.send({"id": quit_request["id"], "result": {}})
        h.send({"id": "c1", "method": "window.before_close", "params": {"window_id": "w1", "reason": "user"}})
        assert h.recv()["id"] == "c1"
        assert oracle.recv_or_none(h.sock, 0.5) is None  # quit is requested at most once
    finally:
        h.close()


def test_rr2_done_callback_waiting_on_another_future_does_not_deadlock(host):
    """review3/chain.py: a done-callback waiting on a second call_async future hung forever."""
    out = {}

    def done(_f):
        try:
            out["inner"] = host.client.call_async("window.get").result(timeout=3)
        except Exception as error:
            out["inner"] = type(error).__name__
    host.client.call_async("window.list").add_done_callback(done)
    first = host.recv()
    host.send({"id": first["id"], "result": []})
    second = host.recv()
    host.send({"id": second["id"], "result": {"ok": 1}})
    deadline = time.monotonic() + 4
    while "inner" not in out and time.monotonic() < deadline:
        time.sleep(0.01)
    assert out.get("inner") == {"ok": 1}, out


@pytest.mark.parametrize("wrapper", ["wait_for", "create_task", "gather"])
def test_rr3_stop_from_wrapper_task_inside_callback_does_not_hang(wrapper):
    """review3/waitfor.py: stop() awaited through wait_for/create_task/gather inside a callback hung."""
    from nativehtmlkit.asyncio_api import EventDispatcher

    async def main():
        dispatcher = EventDispatcher()
        done = asyncio.Event()

        async def callback(_):
            if wrapper == "wait_for":
                await asyncio.wait_for(dispatcher.stop(), 2)
            elif wrapper == "create_task":
                await asyncio.create_task(dispatcher.stop())
            else:
                await asyncio.gather(dispatcher.stop())
            done.set()
        dispatcher.submit(callback, 1)
        await asyncio.wait_for(done.wait(), 4)
        await asyncio.wait_for(dispatcher._task, 4)
    asyncio.run(main())


def test_rr4_host_wrapper_passes_diagnostics_level_unchanged(monkeypatch, tmp_path):
    """Core 1.0.3 relays backend output at every level (NHK-CROSS-0007 fixed): the host wrapper, like every
    launch path, now passes `off` through unchanged (the 0.1.0 interim off->normal mapping is gone)."""
    from nativehtmlkit import launcher
    fake = tmp_path / launcher.HOST_NAME
    fake.write_bytes(b"x")
    monkeypatch.setenv("NATIVEHTMLKIT_HOST_BINARY", str(fake))
    monkeypatch.setenv("NATIVEHTMLKIT_DIAGNOSTICS", "off")
    monkeypatch.setattr(sys, "argv", ["nativehtmlkit-python-host", "run", "--app", "a.toml"])
    seen = {}
    monkeypatch.setattr(launcher.os, "execve", lambda path, args, env: seen.update(env=env) or (_ for _ in ()).throw(SystemExit(0)), raising=False)
    monkeypatch.setattr(launcher.subprocess, "call", lambda args, env=None: seen.update(env=env) or 0)
    try:
        launcher.main()
    except SystemExit:
        pass
    assert seen["env"]["NATIVEHTMLKIT_DIAGNOSTICS"] == "off"
    assert "NATIVEHTMLKIT_SDK_DIAGNOSTICS" not in seen["env"]


def test_m06_string_values_must_be_short_identifiers():
    """Mutant M06: free-form strings under innocuous keys must still be redacted (shape rule)."""
    fields = diagnostics._safe({"window_id": "w1 typed secret", "element": "x" * 200, "reason": "a/b",
                                "event_type": "submit"})
    assert fields == {"window_id": "[REDACTED]", "element": "[REDACTED]", "reason": "[REDACTED]",
                      "event_type": "submit"}


def test_rr5_external_stop_while_callback_runs_still_drains():
    """Regression found by the Windows 3.11 run: an EXTERNAL stop() during a running callback
    must wait for it and for the callbacks queued behind it."""
    from nativehtmlkit.asyncio_api import EventDispatcher

    async def main():
        dispatcher = EventDispatcher()
        gate, started, seen = asyncio.Event(), asyncio.Event(), []

        async def slow(value):
            started.set()
            await gate.wait()
            seen.append(value)
        dispatcher.submit(slow, 1)
        dispatcher.submit(seen.append, 2)
        await started.wait()
        stopper = asyncio.create_task(dispatcher.stop())
        await asyncio.sleep(0.05)
        assert not stopper.done()  # waits for the running callback
        gate.set()
        await asyncio.wait_for(stopper, 3)
        return seen
    assert asyncio.run(main()) == [1, 2]
