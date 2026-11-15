"""Independent wire-v1 framing oracle for fake hosts (FR-PY-17).

Written from protocol/README.md §2 only — deliberately NOT using the SDK's
read_frame/encode_frame/write_all, so a symmetric framing bug in the SDK cannot hide
behind a fake host that shares the same code.
"""
from __future__ import annotations

import json
import socket
import struct


def send(sock: socket.socket, message: dict) -> None:
    body = json.dumps(message, ensure_ascii=False).encode("utf-8")
    sock.sendall(struct.pack(">I", len(body)) + body)


def send_raw(sock: socket.socket, body: bytes) -> None:
    sock.sendall(struct.pack(">I", len(body)) + body)


def _exact(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        piece = sock.recv(size - len(data))
        if not piece:
            raise EOFError("peer closed")
        data += piece
    return data


def recv(sock: socket.socket, timeout: float = 5.0) -> dict:
    sock.settimeout(timeout)
    (length,) = struct.unpack(">I", _exact(sock, 4))
    assert 0 < length <= 2 * 1024 * 1024, length
    return json.loads(_exact(sock, length).decode("utf-8"))


def recv_or_none(sock: socket.socket, timeout: float) -> dict | None:
    try:
        return recv(sock, timeout)
    except (socket.timeout, TimeoutError):
        return None
