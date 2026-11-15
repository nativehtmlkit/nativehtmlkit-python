"""Black-box lifecycle/contract tests added for mutation survivors (REVIEW.md PY-26).

Each test pins one SDK-AUTHORING / README §7 rule against an in-process fake host.
"""
from __future__ import annotations

import os
import socket
import tempfile
import threading
from pathlib import Path

import pytest

from nativehtmlkit import _bootstrap
from nativehtmlkit.application import Application, Document, StaleDocumentError, Window
from nativehtmlkit.client import ProtocolError, RpcClient, SocketStream, encode_frame, read_frame, write_all


@pytest.fixture
def pair():
    a, b = socket.socketpair()
    b.settimeout(5)
    client = RpcClient(SocketStream(a), ordered_notifications=True)
    peer = SocketStream(b)
    yield client, peer
    client.close()
    peer.close()


def send(peer, message):
    write_all(peer, encode_frame({"jsonrpc": "2.0", **message}))


def test_default_host_requests_are_answered_allow(pair):
    client, peer = pair
    send(peer, {"id": "h1", "method": "window.before_close", "params": {"window_id": "w1", "reason": "user"}})
    send(peer, {"id": "h2", "method": "app.before_quit", "params": {"reason": "last_window"}})
    answers = {m["id"]: m for m in (read_frame(peer), read_frame(peer))}
    assert answers["h1"]["result"] == {"allow": True}
    assert answers["h2"]["result"] == {"allow": True}


def test_events_for_replaced_document_are_not_delivered(pair):
    client, peer = pair
    app = Application(client)
    window = Window(app, "w1")
    old, new = Document(window, "d1"), Document(window, "d2")
    app._windows["w1"] = window
    window.document = new
    seen, done = [], threading.Event()
    old._handlers.append(("click", None, lambda e: seen.append(("old", e["document_id"]))))
    new.on("click", lambda e: (seen.append(("new", e["document_id"])), done.set()))
    send(peer, {"method": "document.event", "params": {"window_id": "w1", "document_id": "d1",
                "event": {"type": "click"}}})
    send(peer, {"method": "document.event", "params": {"window_id": "w1", "document_id": "d2",
                "event": {"type": "click"}}})
    assert done.wait(3)
    assert seen == [("new", "d2")]


def test_stale_handle_after_replace_rejected_locally_before_any_rpc(pair):
    client, peer = pair
    app = Application(client)
    window = Window(app, "w1")
    app._windows["w1"] = window
    old = Document(window, "d1")
    window.document = old
    window.document = Document(window, "d2")  # replacement became current
    with pytest.raises(StaleDocumentError):
        old.set_text("status", "never sent")
    # Nothing was written to the host for the stale handle.
    peer.sock.settimeout(0.2)
    with pytest.raises(socket.timeout):
        peer.sock.recv(1)


def test_delegated_handler_matches_identified_ancestor_in_path(pair):
    client, peer = pair
    app = Application(client)
    window = Window(app, "w1")
    document = Document(window, "d1")
    window.document = document
    app._windows["w1"] = window
    done = threading.Event()
    document.on("click", lambda e: done.set(), element="toolbar")
    send(peer, {"method": "document.event", "params": {"window_id": "w1", "document_id": "d1",
                "event": {"type": "click", "element": "save", "path": ["save", "toolbar"]}}})
    assert done.wait(3)


def test_forget_host_environment_scrubs_wire_names_and_marker(monkeypatch):
    for name in ("UI4ME_ENDPOINT", "UI4ME_TOKEN", "UI4ME_APP_ID", "UI4ME_PROTOCOL_VERSION", "UI4ME_DIRECT_START"):
        monkeypatch.setenv(name, "x")
    _bootstrap.forget_host_environment()
    assert not [k for k in os.environ if k.startswith("UI4ME_")]


@pytest.mark.skipif(not hasattr(socket, "AF_UNIX"), reason="Unix socket fake host")
@pytest.mark.parametrize("version", [2, None])
def test_hello_requires_protocol_v1_and_still_scrubs_credentials(monkeypatch, version):
    folder = tempfile.mkdtemp(prefix="nhk-hello-")
    path = os.path.join(folder, "s")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(path)
    server.listen(1)
    seen = {}

    def host():
        conn, _ = server.accept()
        stream = SocketStream(conn)
        hello = read_frame(stream)
        seen["hello"] = hello
        result = {"host_version": "1.0.2", "app_id": "a.b", "capabilities": {}}
        if version is not None:
            result["protocol_version"] = version
        write_all(stream, encode_frame({"jsonrpc": "2.0", "id": hello["id"], "result": result}))
        try:
            conn.recv(1)
        except OSError:
            pass
        conn.close()

    thread = threading.Thread(target=host, daemon=True)
    thread.start()
    token = "ab" * 32
    monkeypatch.setenv("UI4ME_ENDPOINT", path)
    monkeypatch.setenv("UI4ME_TOKEN", token)
    monkeypatch.setenv("UI4ME_APP_ID", "a.b")
    monkeypatch.setenv("UI4ME_PROTOCOL_VERSION", "1")
    try:
        with pytest.raises(ProtocolError):
            RpcClient.from_environment()
    finally:
        thread.join(3)
        server.close()
        Path(path).unlink(missing_ok=True)
        os.rmdir(folder)
    assert seen["hello"]["method"] == "host.hello"
    assert seen["hello"]["params"]["token"] == token and seen["hello"]["params"]["protocol_version"] == 1
    assert not [k for k in os.environ if k.startswith("UI4ME_")]
