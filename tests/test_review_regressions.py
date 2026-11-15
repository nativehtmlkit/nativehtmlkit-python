"""Reproducing tests for the 2026-11-15 source review findings (PY-xx IDs, see REVIEW.md).

Every test here was written to FAIL against the pre-review source and pass after the fix.
They use an in-process socketpair "fake host" only; real-host coverage lives in
``tests/integration``.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from nativehtmlkit import diagnostics
from nativehtmlkit.application import Application, StaleDocumentError, Window, Document
from nativehtmlkit.asyncio_api import AsyncApplication, AsyncRpcClient, EventDispatcher
from nativehtmlkit.client import (DisconnectedError, RpcClient, RpcError, SocketStream,
                                  encode_frame, read_frame, write_all)
from nativehtmlkit.errors import (NativeHTMLKitError, RpcTimeoutError, StaleHandleError,
                                  HostDisconnectedError)

ROOT = Path(__file__).resolve().parents[1]


class FakeHost:
    """Socketpair peer speaking the v1 framing; records every frame it receives."""

    def __init__(self, *, ordered: bool = True):
        a, b = socket.socketpair()
        b.settimeout(5)
        self.sock = b
        self.peer = SocketStream(b)
        self.client = RpcClient(SocketStream(a), ordered_notifications=ordered)

    def read(self):
        return read_frame(self.peer)

    def send(self, message):
        write_all(self.peer, encode_frame({"jsonrpc": "2.0", **message}))

    def reply(self, request, result):
        self.send({"id": request["id"], "result": result})

    def close(self):
        self.client.close()
        self.peer.close()


@pytest.fixture
def host():
    h = FakeHost()
    yield h
    h.close()


def run(coro):
    return asyncio.run(coro)


# PY-01: asyncio deadline must be an explicit outcome-unknown error, not a bare TimeoutError.
def test_py01_async_deadline_is_outcome_unknown(host):
    async def main():
        adapter = AsyncRpcClient(host.client)
        with pytest.raises(RpcTimeoutError) as err:
            await adapter.call("window.list", timeout=0.05)
        assert err.value.outcome_unknown is True
        assert err.value.operation == "window.list"
        assert err.value.request_id
    run(main())
    first = host.read()
    assert first["method"] == "window.list"
    # The SDK asks the host to cancel the abandoned request (advisory; not a rollback).
    cancel = host.read()
    assert cancel["method"] == "request.cancel" and cancel["params"] == {"id": first["id"]}


# PY-02: a disconnect fails every pending request with operation, request id and cause.
def test_py02_disconnect_preserves_cause_operation_and_count(host):
    futures = [host.client.call_async("document.command", {"n": i}) for i in range(3)]
    for _ in futures:
        host.read()
    started = time.monotonic()
    host.peer.close()
    errors = []
    for future in futures:
        with pytest.raises(DisconnectedError) as err:
            future.result(3)
        errors.append(err.value)
    assert time.monotonic() - started < 2
    for error in errors:
        assert error.operation == "document.command"
        assert error.request_id and error.request_id.startswith("py-")
        assert error.outcome_unknown is True
        assert error.__cause__ is not None  # causal transport error is retained
        assert error.pending_failed == 3


# PY-03: host RPC errors carry the operation and request id (error-quality baseline).
def test_py03_rpc_error_carries_operation_and_request_id(host):
    future = host.client.call_async("window.get", {"window_id": "w9"})
    request = host.read()
    host.send({"id": request["id"], "error": {"code": -32004, "message": "closed"}})
    with pytest.raises(RpcError) as err:
        future.result(3)
    assert err.value.code == -32004
    assert err.value.operation == "window.get"
    assert err.value.request_id == request["id"]


# PY-04: session IDs from Core/CLI use [A-Za-z0-9._:-]{1,128}; the SDK must keep them.
@pytest.mark.parametrize("session", ["nhk:cli.1234", "abc", "a" * 128])
def test_py04_session_id_alphabet_matches_core(session):
    code = "import nativehtmlkit.diagnostics as d; print(d.SESSION_ID)"
    env = dict(os.environ, NATIVEHTMLKIT_DIAGNOSTIC_SESSION_ID=session, PYTHONPATH=str(ROOT / "src"))
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    assert out.stdout.strip() == session


def test_py04_invalid_session_id_replaced_with_core_compatible_one():
    code = "import nativehtmlkit.diagnostics as d, os; print(d.SESSION_ID); print(os.environ['NATIVEHTMLKIT_DIAGNOSTIC_SESSION_ID'])"
    env = dict(os.environ, NATIVEHTMLKIT_DIAGNOSTIC_SESSION_ID="bad id/with space", PYTHONPATH=str(ROOT / "src"))
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True)
    generated, exported = out.stdout.split()
    assert generated == exported != "bad id/with space"
    assert all(c.isalnum() or c in "._:-" for c in generated) and len(generated) <= 128


# PY-05: `python -m nativehtmlkit support` must include the recorded session, re-sanitized.
def test_py05_support_command_collects_recorded_session(tmp_path):
    sentinel = "nhkSENTINEL" + "0xC0FFEE"
    folder = tmp_path / "diag"
    folder.mkdir()
    good = {"schema_version": 1, "timestamp": "2026-11-15T00:00:00+00:00", "session_id": "sess-1",
            "component": "python-sdk", "pid": 1, "level": "TRACE", "event": "rpc.completed",
            "context": {"method": "document.command", "duration_ms": 3}}
    # A tampered/foreign record that smuggles a secret must be re-redacted on export.
    bad = dict(good, event="rpc.started", context={"method": sentinel + " typed", "token": sentinel})
    (folder / "python-sess-1-1.jsonl").write_text(json.dumps(good) + "\n" + json.dumps(bad) + "\n" + "not json\n")
    (folder / "python-other-2.jsonl").write_text(json.dumps(dict(good, session_id="other")) + "\n")
    out = tmp_path / "support.zip"
    env = dict(os.environ, NATIVEHTMLKIT_DIAGNOSTICS_DIR=str(folder), PYTHONPATH=str(ROOT / "src"))
    env.pop("NATIVEHTMLKIT_DIAGNOSTICS", None)
    subprocess.run([sys.executable, "-m", "nativehtmlkit", "support", str(out), "--session", "sess-1"],
                   env=env, check=True, capture_output=True, text=True)
    with zipfile.ZipFile(out) as archive:
        names = set(archive.namelist())
        blob = b"".join(archive.read(n) for n in names)
        manifest = json.loads(archive.read("manifest.json"))
        timeline = [json.loads(l) for l in archive.read("timeline.jsonl").decode().splitlines()]
    assert sentinel.encode() not in blob
    assert {r["event"] for r in timeline} >= {"rpc.completed", "rpc.started"}
    assert all(r["session_id"] == "sess-1" for r in timeline)
    assert manifest["collected_files"] == 1
    assert manifest["invalid_lines"] == 1
    assert not any(n.endswith((".log", ".png", ".txt")) for n in names)  # never raw stderr/screenshots


# PY-06: ring-buffer eviction is lost evidence and must be disclosed.
def test_py06_history_eviction_disclosed(tmp_path):
    recorder = diagnostics.DiagnosticRecorder(level="trace", directory=tmp_path, max_history=3)
    for i in range(5):
        recorder.record("rpc.completed", level="TRACE", duration_ms=i)
    recorder.close()
    summary = recorder.summary()
    assert summary["records"] == 3
    assert summary["history_evicted"] == 2


# PY-07: trace records correlate host event -> callback -> RPC (UI mutation op).
def test_py07_trace_correlates_event_callback_and_rpc(host, monkeypatch, tmp_path):
    recorder = diagnostics.DiagnosticRecorder(level="trace", directory=tmp_path)
    monkeypatch.setattr(diagnostics, "_recorder", recorder)
    app = Application(host.client)
    window = Window(app, "w1")
    document = Document(window, "d1")
    window.document = document
    app._windows["w1"] = window
    done = threading.Event()

    def on_submit(_event):
        document.set_text("status", "secret-typed-value")
        done.set()

    document.on("submit", on_submit, element="form")
    host.send({"method": "document.event", "params": {"window_id": "w1", "document_id": "d1",
               "event": {"type": "submit", "element": "form", "path": ["form"]}}})
    command = host.read()
    host.reply(command, {})
    assert done.wait(3)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        events = [r["event"] for r in recorder.history()]
        if "callback.completed" in events:
            break
        time.sleep(0.01)
    history = recorder.history()
    by_event = {}
    for item in history:
        by_event.setdefault(item["event"], []).append(item["context"])
    received = by_event["host.notification"][0]
    assert received["method"] == "document.event" and received["event_type"] == "submit"
    seq = received["event_seq"]
    assert by_event["callback.started"][0]["event_seq"] == seq
    rpc = [c for c in by_event["rpc.started"] if c.get("method") == "document.command"][0]
    assert rpc["cause_seq"] == seq and rpc["op"] == "set_text"
    assert [c for c in by_event["rpc.completed"] if c["request_id"] == rpc["request_id"]]
    assert by_event["callback.completed"][0]["event_seq"] == seq
    assert "secret-typed-value" not in json.dumps(history)


# PY-08 / PY-09: run() is idempotent and a deliberate local close is not a "disconnect".
def test_py08_run_is_idempotent_shutdown_hooks_once(host):
    app = Application(host.client)
    calls = []
    app.on_shutdown(lambda: calls.append(1))
    app._ready = True
    host.send({"method": "app.shutdown", "params": {"deadline_ms": 1000}})
    app.run()
    app.run()
    assert calls == [1]


def test_py09_local_close_from_callback_ends_run_cleanly(host):
    app = Application(host.client)
    app._ready = True
    timer = threading.Timer(0.1, app.close)
    timer.start()
    started = time.monotonic()
    app.run()  # must return, not raise DisconnectedError
    assert time.monotonic() - started < 2


def test_py09_host_disconnect_still_raises(host):
    app = Application(host.client)
    app._ready = True
    threading.Timer(0.1, host.peer.close).start()
    with pytest.raises(DisconnectedError):
        app.run()


# PY-10: cancelling AsyncApplication.run() must finish deterministically.
def test_py10_async_run_cancellation_is_bounded(host):
    app = Application(host.client)
    app._ready = True

    async def main():
        adapter = AsyncApplication(app)
        task = asyncio.create_task(adapter.run())
        await asyncio.sleep(0.1)
        task.cancel()
        started = time.monotonic()
        with pytest.raises(asyncio.CancelledError):
            await task
        return time.monotonic() - started

    elapsed = run(asyncio.wait_for(main(), 5))
    assert elapsed < 2
    assert host.client.closed


# PY-11: no callback may start after its subscription was disposed.
def test_py11_unsubscribed_async_callback_not_invoked(host):
    app = Application(host.client)
    window = Window(app, "w1")
    document = Document(window, "d1")
    window.document = document
    app._windows["w1"] = window
    seen = []

    async def main():
        adapter = AsyncApplication(app)
        gate = asyncio.Event()

        async def slow(event):
            seen.append(("slow", event["n"]))
            await gate.wait()

        def later(event):
            seen.append(("later", event["n"]))

        adapter.on_document_event(document, "click", slow)
        unsubscribe = adapter.on_document_event(document, "input", later)
        host.send({"method": "document.event", "params": {"window_id": "w1", "document_id": "d1",
                   "event": {"type": "click", "n": 1}}})
        host.send({"method": "document.event", "params": {"window_id": "w1", "document_id": "d1",
                   "event": {"type": "input", "n": 2}}})
        for _ in range(100):
            if adapter.dispatcher.queue.qsize() >= 1 and seen:
                break
            await asyncio.sleep(0.01)
        unsubscribe()  # the queued "input" event must now be discarded
        gate.set()
        await asyncio.sleep(0.05)
        await adapter.dispatcher.stop()

    run(asyncio.wait_for(main(), 5))
    assert seen == [("slow", 1)]


# PY-12: a callback raising CancelledError must not kill the dispatcher.
def test_py12_dispatcher_survives_callback_cancelled_error():
    async def main():
        dispatcher = EventDispatcher(capacity=4)
        seen = []

        async def bad(_):
            raise asyncio.CancelledError()

        dispatcher.submit(bad, 1)
        dispatcher.submit(seen.append, 2)
        for _ in range(100):
            if seen:
                break
            await asyncio.sleep(0.01)
        await asyncio.wait_for(dispatcher.stop(), 2)
        return seen

    assert run(main()) == [2]


# PY-13: submitting after the owning loop closed is counted, not raised into the worker.
def test_py13_submit_after_loop_closed_is_counted():
    loop = asyncio.new_event_loop()
    dispatcher = loop.run_until_complete(_make_dispatcher())
    loop.run_until_complete(dispatcher.stop())
    loop.close()
    dispatcher._closed = False  # simulate a race where stop() was not observed yet
    dispatcher.submit(lambda _: None, 1)
    assert dispatcher.dropped == 1


async def _make_dispatcher():
    return EventDispatcher()


# PY-14: stale handles are part of the SDK error taxonomy.
def test_py14_stale_document_error_is_typed():
    error = StaleDocumentError("gone")
    assert isinstance(error, StaleHandleError)
    assert isinstance(error, NativeHTMLKitError)
    assert isinstance(error, RuntimeError)  # backwards compatible
    assert error.code == "NHK-HANDLE-STALE"


# PY-15: `doctor` against a hung host reports a timeout instead of a traceback.
@pytest.mark.skipif(os.name == "nt", reason="uses a POSIX shell script as a fake host")
def test_py15_doctor_timeout_is_reported(tmp_path, monkeypatch):
    fake = tmp_path / "nativehtmlkit-host"
    fake.write_text("#!/bin/sh\nsleep 30\n")
    fake.chmod(0o755)
    from nativehtmlkit import __main__ as cli
    monkeypatch.setenv("NATIVEHTMLKIT_HOST_BINARY", str(fake))
    monkeypatch.setattr(cli, "DOCTOR_TIMEOUT_S", 0.5)
    assert cli.main(["doctor"]) == 1


# PY-16: generated projects and docs must name a launcher the wheel actually installs.
def test_py16_scaffold_names_installed_host_launcher():
    from nativehtmlkit.scaffold import templates
    try:
        import tomllib
    except ModuleNotFoundError:  # Python 3.10
        tomllib = pytest.importorskip("tomli")
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["scripts"]
    files = templates("Hello", "/usr/bin/python3")
    assert "nativehtmlkit-python-host run --app app.toml" in files["app.toml"]
    assert "nativehtmlkit-python-host" in scripts
    assert "nativehtmlkit-host" not in scripts  # Core owns that executable name


# PY-19: the contract snapshot is pinned by SHA and covers every method the SDK sends.
def test_py19_contract_pinned_and_covers_sdk_methods():
    import hashlib
    import re
    source = json.loads((ROOT / "contracts/SOURCE.json").read_text())
    data = (ROOT / "contracts/core-v1-method-matrix.json").read_bytes()
    assert hashlib.sha256(data).hexdigest() == source["sha256"]
    matrix = json.loads(data)
    methods = {k for k, v in matrix["methods"].items() if v["direction"] == "client->host"}
    ops = set(matrix["document_command_ops"])
    sent, used_ops = set(), set()
    for path in (ROOT / "src/nativehtmlkit").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        sent |= set(re.findall(r'(?:rpc|client|self)\.call(?:_async)?\("([a-z_]+\.[a-z_]+)"', text))
        sent |= {"dialog." + k for k in re.findall(r'_file_dialog\("([a-z_]+)"', text)}
        sent |= set(re.findall(r'notify\("([a-z_]+\.[a-z_]+)"', text))
        used_ops |= set(re.findall(r'self\.command\("([a-z_]+)"', text))
        used_ops |= set(re.findall(r'_mutate\("([a-z_]+)"', text))
        used_ops |= set(re.findall(r'document\.command\("([a-z_]+)"', text))
    assert {"host.hello", "window.create", "document.load", "document.command", "app.ready",
            "bitmap.present", "request.cancel"} <= sent
    assert sent <= methods, sent - methods
    assert len(used_ops) > 40 and used_ops <= ops, used_ops - ops
    # Every host->client request must be answered by the default client.
    host_requests = {k for k, v in matrix["methods"].items()
                     if v["direction"] == "host->client" and v["kind"] == "request"}
    client = RpcClient.__new__(RpcClient)
    defaults = {"window.before_close", "app.before_quit"}
    assert host_requests == defaults


# PY-20: an unmatched response is a recorded anomaly, not silently dropped.
def test_py20_unmatched_response_recorded(host, monkeypatch, tmp_path):
    recorder = diagnostics.DiagnosticRecorder(level="trace", directory=tmp_path)
    monkeypatch.setattr(diagnostics, "_recorder", recorder)
    host.send({"id": "py-999", "result": {}})
    future = host.client.call_async("window.list")
    host.reply(host.read(), [])
    assert future.result(3) == []
    assert any(r["event"] == "rpc.unmatched_response" for r in recorder.history())


# PY-21: malformed launch token is refused before it is sent anywhere.
def test_py21_token_shape_validated_and_scrubbed(monkeypatch):
    monkeypatch.setenv("UI4ME_ENDPOINT", "/nonexistent/nhk.sock")
    monkeypatch.setenv("UI4ME_TOKEN", "not-a-token")
    from nativehtmlkit.client import ProtocolError
    with pytest.raises(ProtocolError):
        RpcClient.from_environment()
    assert "UI4ME_TOKEN" not in os.environ and "UI4ME_ENDPOINT" not in os.environ


# PY-24: a reply racing the local deadline is returned, not reported as unknown.
def test_py24_reply_racing_deadline_is_not_lost(host, monkeypatch):
    import concurrent.futures
    original = concurrent.futures.Future.result

    def late_result(self, timeout=None):
        if timeout is not None and not self.done():
            request = host.read()
            host.reply(request, {"ok": True})
            deadline = time.monotonic() + 3
            while not self.done() and time.monotonic() < deadline:
                time.sleep(0.005)
            raise concurrent.futures.TimeoutError()
        return original(self, timeout)

    monkeypatch.setattr(concurrent.futures.Future, "result", late_result)
    assert host.client.call("window.list", timeout=0.01) == {"ok": True}


# PY-25: local back-pressure is distinguishable from a host -32005 reply.
def test_py25_local_busy_is_distinguishable(host):
    from nativehtmlkit.client import MAX_PENDING, ClientBusyError
    for _ in range(MAX_PENDING):
        host.client.call_async("pending")
    with pytest.raises(ClientBusyError) as err:
        host.client.call_async("overflow")
    assert err.value.code == -32005 and err.value.local is True
    assert isinstance(err.value, RpcError)


# PY-27: one failing document handler must not suppress the other handlers of the same event.
def test_py27_failing_handler_isolated_from_siblings(host, capsys):
    app = Application(host.client)
    window = Window(app, "w1")
    document = Document(window, "d1")
    window.document = document
    app._windows["w1"] = window
    done = threading.Event()

    def broken(_):
        raise ValueError("boom")
    document.on("click", broken)
    document.on("click", lambda _: done.set())
    host.send({"method": "document.event", "params": {"window_id": "w1", "document_id": "d1",
               "event": {"type": "click"}}})
    assert done.wait(3)


# PY-28: the packaged skill copy must not drift from the canonical skills/ source.
def test_py28_embedded_skill_matches_canonical_source():
    canonical = ROOT / "skills/nativehtmlkit-python"
    embedded = ROOT / "src/nativehtmlkit/_skills/nativehtmlkit-python"
    names = sorted(p.relative_to(canonical).as_posix() for p in canonical.rglob("*") if p.is_file())
    assert names == sorted(p.relative_to(embedded).as_posix() for p in embedded.rglob("*") if p.is_file())
    for name in names:
        assert (canonical / name).read_bytes() == (embedded / name).read_bytes(), name


# PY-29: recorder losses (writer queue overflow) are counted and disclosed.
def test_py29_writer_queue_overflow_counted(tmp_path):
    recorder = diagnostics.DiagnosticRecorder(level="trace", directory=tmp_path, max_pending=2)
    for i in range(5000):
        recorder.record("rpc.completed", level="TRACE", duration_ms=i)
    recorder.close(timeout=5)
    summary = recorder.summary()
    assert summary["dropped"] > 0
    assert summary["dropped"] + len(recorder.path.read_text().splitlines()) == 5000


# ---- Independent re-review findings (PY-41..PY-48) ----
def _host_request(host, rid, method="window.before_close"):
    host.send({"id": rid, "method": method, "params": {"window_id": "w1", "reason": "user"}})


# PY-41: an unserializable handler result must produce an error reply, not kill the worker.
def test_py41_unserializable_result_answered_and_worker_survives(host):
    host.client.on_request("custom.q", lambda p: {"x": {1, 2}})
    _host_request(host, "h1", "custom.q")
    reply = host.read()
    assert reply["id"] == "h1" and reply["error"]["code"] == -32603
    for i in range(6):  # more than the 4 pool workers
        _host_request(host, f"b{i}")
        assert host.read()["result"] == {"allow": True}


# PY-42: transient local back-pressure on a reply must not retire request workers.
def test_py42_busy_reply_does_not_retire_workers(host, monkeypatch):
    from nativehtmlkit.client import ClientBusyError
    real = host.client._enqueue
    failures = {"left": 5}

    def flaky(message):
        if "result" in message and failures["left"]:
            failures["left"] -= 1
            raise ClientBusyError("Outgoing queue is full")
        return real(message)
    monkeypatch.setattr(host.client, "_enqueue", flaky)
    for i in range(5):
        _host_request(host, f"x{i}")
    deadline = time.monotonic() + 5
    while failures["left"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert failures["left"] == 0
    monkeypatch.setattr(host.client, "_enqueue", real)
    _host_request(host, "after")
    answers = {}
    deadline = time.monotonic() + 5
    host.sock.settimeout(3)
    while "after" not in answers and time.monotonic() < deadline:
        try:
            message = host.read()
        except (OSError, Exception):
            break
        answers[message["id"]] = message
    assert "after" in answers and answers["after"]["result"] == {"allow": True}
    assert not host.client.closed


# PY-43: SystemExit in an event callback must not kill the ordered event worker.
def test_py43_systemexit_in_callback_keeps_event_delivery(host):
    seen = []

    def handler(params):
        seen.append(params["n"])
        if params["n"] == 1:
            raise SystemExit(3)
    host.client.on_notification("demo.event", handler)
    for n in (1, 2, 3):
        host.send({"method": "demo.event", "params": {"n": n}})
    deadline = time.monotonic() + 3
    while len(seen) < 3 and time.monotonic() < deadline:
        time.sleep(0.01)
    assert seen == [1, 2, 3]


# PY-44: app.shutdown followed by EOF is an orderly shutdown even if workers are busy.
def test_py44_shutdown_then_eof_is_orderly(host):
    app = Application(host.client)
    app._ready = True
    gate = threading.Event()
    host.client.on_request("slow.policy", lambda p: gate.wait(5) and {})
    for i in range(4):  # occupy every pool worker
        host.send({"id": f"s{i}", "method": "slow.policy", "params": {}})
    time.sleep(0.2)
    host.send({"method": "app.shutdown", "params": {"deadline_ms": 1000}})
    time.sleep(0.1)
    host.peer.close()
    try:
        app.run()  # must not raise DisconnectedError
    finally:
        gate.set()
    assert host.client.shutdown_requested.is_set()


# PY-45: export after the recorder was closed must not hang.
def test_py45_export_after_close_does_not_hang(tmp_path, monkeypatch):
    recorder = diagnostics.DiagnosticRecorder(level="trace", directory=tmp_path)
    monkeypatch.setattr(diagnostics, "_recorder", recorder)
    recorder.close()
    recorder.record("rpc.completed", level="TRACE", duration_ms=1)
    done = threading.Event()
    thread = threading.Thread(target=lambda: (diagnostics.export_bundle(tmp_path / "s.zip", directory=tmp_path), done.set()),
                              daemon=True)
    thread.start()
    assert done.wait(3)


# PY-46: a full outgoing queue while refusing a host request must not tear down the connection.
def test_py46_busy_while_rejecting_host_request_keeps_connection(host, monkeypatch):
    from nativehtmlkit.client import ClientBusyError
    import queue as queue_module
    gate = threading.Event()
    host.client.on_request("slow.policy", lambda p: gate.wait(5) and {})

    class Full:
        def put_nowait(self, _):
            raise queue_module.Full

    real_queue, real_enqueue = host.client._callbacks, host.client._enqueue
    monkeypatch.setattr(host.client, "_callbacks", Full())
    monkeypatch.setattr(host.client, "_enqueue", lambda m: (_ for _ in ()).throw(ClientBusyError("full")))
    host.send({"id": "q1", "method": "slow.policy", "params": {}})
    time.sleep(0.3)
    assert not host.client.closed
    gate.set()


# PY-48: a malformed HOST-MANIFEST.json is reported, not a traceback.
def test_py48_version_with_malformed_manifest(tmp_path, monkeypatch, capsys):
    from nativehtmlkit import launcher, __main__ as cli
    fake_bin = tmp_path / "_bin"
    fake_bin.mkdir()
    (fake_bin / "HOST-MANIFEST.json").write_text("[1, 2]")
    host_file = fake_bin / launcher.HOST_NAME
    host_file.write_bytes(b"\x7fELF fake")
    monkeypatch.setattr(launcher, "bundled_host_path", lambda: host_file)
    monkeypatch.delenv("NATIVEHTMLKIT_HOST_BINARY", raising=False)
    monkeypatch.delenv("UI4ME_HOST_BINARY", raising=False)
    assert cli.main(["version"]) == 1
    assert '"invalid"' in capsys.readouterr().out


# PY-49: a host BUSY refusal of bitmap.create (Core 1.0.2 256 MiB budget) is a typed host error
# and leaves no SDK-side bitmap state behind.
def test_py49_bitmap_budget_busy_is_typed_and_leaves_no_state(host):
    app = Application(host.client)
    window = Window(app, "w1")
    document = Document(window, "d1")
    window.document = document
    app._windows["w1"] = window
    result = {}

    def create():
        try:
            document.create_bitmap("big", 4096, 4096)
        except Exception as error:
            result["error"] = error
    thread = threading.Thread(target=create)
    thread.start()
    request = host.read()
    assert request["method"] == "bitmap.create"
    host.send({"id": request["id"], "error": {"code": -32005, "message": "live bitmap budget exhausted"}})
    thread.join(3)
    error = result["error"]
    assert isinstance(error, RpcError) and error.code == -32005 and error.local is False
    assert error.operation == "bitmap.create"
    assert document._bitmaps == []


# PY-53 (lead decision on NHK-CROSS-0003): app.shutdown implies every window is closed.
# Events received before it are still delivered; afterwards every handle is stale.
def test_py53_shutdown_marks_all_handles_stale(host):
    app = Application(host.client)
    app._ready = True
    seen = []
    windows = []
    for wid, did in (("w1", "d1"), ("w2", "d2")):
        window = Window(app, wid)
        window.document = Document(window, did)
        app._windows[wid] = window
        windows.append(window)
    windows[0].document.on("click", lambda e: seen.append(e["document_id"]))
    host.send({"method": "document.event", "params": {"window_id": "w1", "document_id": "d1",
               "event": {"type": "click"}}})
    host.send({"method": "app.shutdown", "params": {"deadline_ms": 1000}})
    app.run()
    assert seen == ["d1"]  # delivered before the handles were retired
    for window in windows:
        assert window.closed
        with pytest.raises(StaleDocumentError):
            window.document.set_text("x", "y")
    assert app._windows == {}


# PY-54 (lead decision Q3): a callback worker blocked in user code is not awaited forever
# at close; the join is bounded and the abandonment is recorded.
def test_py54_blocked_event_worker_bounded_close_recorded(host, monkeypatch, tmp_path):
    recorder = diagnostics.DiagnosticRecorder(level="trace", directory=tmp_path)
    monkeypatch.setattr(diagnostics, "_recorder", recorder)
    gate = threading.Event()
    host.client.on_notification("demo.block", lambda p: gate.wait(10))
    host.send({"method": "demo.block", "params": {}})
    time.sleep(0.3)
    started = time.monotonic()
    host.client.close()
    try:
        assert time.monotonic() - started < 3
        events = [r for r in recorder.history() if r["event"] == "callback.worker_abandoned"]
        assert events and events[0]["context"]["threads"] >= 1
        assert all(t.daemon for t in host.client._threads)
    finally:
        gate.set()
