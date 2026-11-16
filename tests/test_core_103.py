"""Core 1.0.3 behaviour the SDK must absorb (fake host via the independent oracle)."""
from __future__ import annotations

import asyncio
import os
import socket
import threading
import time

import pytest

import oracle
from nativehtmlkit import diagnostics
from nativehtmlkit.application import Application
from nativehtmlkit.asyncio_api import AsyncRpcClient
from nativehtmlkit.client import RpcClient, SocketStream


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


# (2) document.load (path/asset_root) may be answered after later requests: correlate by id only.
def test_out_of_order_load_reply_sync(host):
    results = {}

    def load():
        results["load"] = host.client.call("document.load", {"window_id": "w1", "path": "/x.html"})

    def get():
        results["get"] = host.client.call("window.get", {"window_id": "w1"})
    t1 = threading.Thread(target=load)
    t1.start()
    load_request = host.recv()
    t2 = threading.Thread(target=get)
    t2.start()
    get_request = host.recv()
    assert load_request["method"] == "document.load" and get_request["method"] == "window.get"
    host.send({"id": get_request["id"], "result": {"window_id": "w1", "title": "t"}})
    t2.join(3)
    assert results.get("get") == {"window_id": "w1", "title": "t"} and "load" not in results
    host.send({"id": load_request["id"], "result": {"document_id": "d7"}})
    t1.join(3)
    assert results["load"] == {"document_id": "d7"}


def test_out_of_order_load_reply_asyncio(host):
    async def main():
        rpc = AsyncRpcClient(host.client)
        load = asyncio.create_task(rpc.call("document.load", {"window_id": "w1", "asset_root": "/a", "path": "/a/i.html"}))
        await asyncio.sleep(0.05)
        load_request = await asyncio.to_thread(host.recv)
        later = asyncio.create_task(rpc.call("window.list"))
        later_request = await asyncio.to_thread(host.recv)
        host.send({"id": later_request["id"], "result": [{"window_id": "w1"}]})
        assert await asyncio.wait_for(later, 3) == [{"window_id": "w1"}]
        assert not load.done()
        host.send({"id": load_request["id"], "result": {"document_id": "d9"}})
        assert await asyncio.wait_for(load, 3) == {"document_id": "d9"}
    asyncio.run(main())


# (3) A blocked application callback must never stop the reader (the host would then drop or fail).
def test_blocked_callback_never_blocks_reader_and_drops_are_counted(host, monkeypatch, tmp_path):
    recorder = diagnostics.DiagnosticRecorder(level="debug", directory=tmp_path)
    monkeypatch.setattr(diagnostics, "_recorder", recorder)
    gate = threading.Event()
    host.client.on_notification("document.event", lambda _p: gate.wait(10))
    future = host.client.call_async("window.list")
    request = host.recv()
    for i in range(300):  # far beyond the SDK's 128-event queue while the callback blocks
        host.send({"method": "document.event", "params": {"window_id": "w1", "document_id": "d1",
                   "event": {"type": "input", "n": i}}})
    started = time.monotonic()
    host.send({"id": request["id"], "result": []})
    try:
        assert future.result(3) == [] and time.monotonic() - started < 2  # reader kept reading
        assert host.client.dropped_notifications > 0
        assert any(r["event"] == "rpc.notification_dropped" for r in recorder.history())
    finally:
        gate.set()


def test_host_dropped_notifications_recorded_at_shutdown(host, monkeypatch, tmp_path):
    recorder = diagnostics.DiagnosticRecorder(level="normal", directory=tmp_path)
    monkeypatch.setattr(diagnostics, "_recorder", recorder)
    app = Application(host.client)
    app._ready = True

    def serve():
        message = host.recv()
        assert message["method"] == "host.diagnostics"
        host.send({"id": message["id"], "result": {"dropped_notifications": 5, "logging": {}}})
    threading.Thread(target=serve, daemon=True).start()
    host.send({"method": "app.shutdown", "params": {"deadline_ms": 1000}})
    app.run()
    dropped = [r for r in recorder.history() if r["event"] == "host.notifications_dropped"]
    assert dropped and dropped[0]["context"]["dropped"] == 5 and dropped[0]["level"] == "WARN"
    assert app.host_dropped_notifications == 5


# (1) NHK-CROSS-0007 fixed in Core 1.0.3: `off` reaches the host unchanged.
def test_off_is_passed_to_the_host_unchanged(monkeypatch):
    from nativehtmlkit import _bootstrap
    seen = {}

    class FakeStderr(list):
        def close(self):
            pass

    class FakeProcess:
        stderr = FakeStderr()

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0
    monkeypatch.setattr(_bootstrap, "spawn_host", lambda command, env: (seen.update(env=env) or FakeProcess(), None))
    assert _bootstrap.run_host(["host"], env={"NATIVEHTMLKIT_DIAGNOSTICS": "off"}) == 0
    assert seen["env"]["NATIVEHTMLKIT_DIAGNOSTICS"] == "off"
    assert "NATIVEHTMLKIT_SDK_DIAGNOSTICS" not in seen["env"]


def test_version_reports_host_source_identity(tmp_path, monkeypatch, capsys):
    """(8) `version` runs `host --version --verbose` and cross-checks it with HOST-MANIFEST.json."""
    import hashlib
    import json
    from nativehtmlkit import launcher, __main__ as cli
    if os.name == "nt":
        pytest.skip("POSIX shell fake host")
    folder = tmp_path / "_bin"
    folder.mkdir()
    identity = {"name": "nativehtmlkit-host", "version": "1.0.3", "source_commit": "a" * 40, "source_dirty": False,
                "source_tree": "b" * 40}
    host = folder / launcher.HOST_NAME
    host.write_text("#!/bin/sh\nif [ \"$1 $2\" = \"--version --verbose\" ]; then echo '%s'; fi\n" % json.dumps(identity))
    host.chmod(0o755)
    manifest = {"host_sha256": hashlib.sha256(host.read_bytes()).hexdigest(), "host_file": host.name,
                "protocol_version": 1, "host_source_identity": identity}
    (folder / "HOST-MANIFEST.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(launcher, "bundled_host_path", lambda: host)
    monkeypatch.delenv("NATIVEHTMLKIT_HOST_BINARY", raising=False)
    assert cli.main(["version"]) == 0
    info = json.loads(capsys.readouterr().out)
    assert info["host"]["source_identity"] == identity and info["host"]["source_identity_match"] is True
    identity["source_commit"] = "c" * 40
    manifest["host_source_identity"] = identity
    (folder / "HOST-MANIFEST.json").write_text(json.dumps(manifest))
    assert cli.main(["version"]) == 1
    assert json.loads(capsys.readouterr().out)["host"]["source_identity_match"] is False
