"""NativeHTMLKit host IPC client, using only the Python standard library.

Most applications use ``nativehtmlkit.Application``; this module is the transport
underneath it. The reader and writer never run application callbacks. Callbacks may therefore
await host RPCs. Both directions use the same length-prefixed JSON-RPC profile.
"""

from __future__ import annotations

import concurrent.futures
import contextvars
import ctypes
import json
import os
import queue
import re
import socket
import struct
import sys
import threading
import time
from typing import Any, Callable
from . import diagnostics
from .errors import (RpcTimeoutError, NativeHTMLKitError, HostDisconnectedError, HostProtocolError,
                     LocalRequestError)

CLIENT_VERSION = "0.1.2"  # Kept equal to nativehtmlkit.__version__ (checked by tests).

MAX_FRAME_BYTES = 2 * 1024 * 1024
MAX_PENDING = 128
MAX_QUEUED_BYTES = 8 * 1024 * 1024
_DEFAULT_TIMEOUT = object()
_TOKEN = re.compile(r"[0-9A-Fa-f]{64}")

# Diagnostics correlation: the host notification (event_seq) whose callback is
# currently running in this thread / asyncio context. RPCs record it as cause_seq.
CAUSE: contextvars.ContextVar[int | None] = contextvars.ContextVar("nativehtmlkit_cause", default=None)


class ProtocolError(HostProtocolError):
    """Malformed or incompatible Core wire message."""


class DisconnectedError(HostDisconnectedError):
    """The authenticated Core host is disconnected; pending outcomes may be unknown."""


class _ClientClosed(DisconnectedError):
    """Marker cause: the application closed the connection itself."""


class RpcError(NativeHTMLKitError):
    """A correlated host RPC error; `code` retains the numeric v1 RPC code.

    ``local`` is False for an error the host returned; :class:`ClientBusyError`
    (local back-pressure) sets it True.
    """
    error_id = classification = "NHK-HOST-RPC"
    local = False

    def __init__(self, code: int, message: str, data: Any = None, *,
                 operation: str | None = None, request_id: str | None = None):
        super().__init__(f"{code}: {message}", data=data, operation=operation, request_id=request_id)
        self.code, self.message, self.data = code, message, data


class ClientBusyError(RpcError):
    """The SDK refused to queue a message (pending/outgoing limit). Nothing was sent."""
    error_id = classification = "NHK-CLIENT-BUSY"
    local = True

    def __init__(self, message: str, *, operation: str | None = None):
        super().__init__(-32005, message, operation=operation)


class SocketStream:
    def __init__(self, sock: socket.socket):
        self.sock = sock

    def read(self, size: int) -> bytes:
        return self.sock.recv(size)

    def write(self, data: bytes | memoryview) -> int:
        return self.sock.send(data)

    def close(self) -> None:
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class NamedPipeStream:
    """Overlapped Windows pipe handle shared by dedicated reader/writer threads.

    Windows serializes all I/O on a synchronous file object, so a blocked read
    would stall every write on the same pipe. Each operation therefore uses its
    own OVERLAPPED/event, and close cancels in-flight operations with CancelIoEx
    before closing the handle once no operation still uses it.
    """

    _ABORTED = (6, 109, 232, 233, 995)

    def __init__(self, name: str, timeout: float = 15.0):
        if os.name != "nt":
            raise OSError("Windows named pipes require Windows")
        if not name.startswith("\\\\.\\pipe\\"):
            raise ValueError("A local named-pipe path is required")
        from ctypes import wintypes

        class OVERLAPPED(ctypes.Structure):
            _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                        ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                        ("hEvent", wintypes.HANDLE)]

        self._overlapped = OVERLAPPED
        self._wintypes = wintypes
        self._dll = ctypes.WinDLL("kernel32", use_last_error=True)
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._in_flight = 0
        self._closed = False
        k = self._dll
        k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
        k.CreateFileW.restype = wintypes.HANDLE
        k.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        k.WaitNamedPipeW.restype = wintypes.BOOL
        for name_ in ("ReadFile", "WriteFile"):
            f = getattr(k, name_)
            f.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                          ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(OVERLAPPED)]
            f.restype = wintypes.BOOL
        k.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(OVERLAPPED),
                                          ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
        k.GetOverlappedResult.restype = wintypes.BOOL
        k.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        k.CreateEventW.restype = wintypes.HANDLE
        k.CancelIoEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
        k.CancelIoEx.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]
        k.CloseHandle.restype = wintypes.BOOL
        deadline = time.monotonic() + timeout
        invalid = ctypes.c_void_p(-1).value
        while True:
            handle = k.CreateFileW(name, 0x80000000 | 0x40000000, 0, None, 3,
                                   0x40000000, None)  # FILE_FLAG_OVERLAPPED
            if handle != invalid:
                self._handle = handle
                return
            error = ctypes.get_last_error()
            if error not in (2, 231) or time.monotonic() >= deadline:
                raise ctypes.WinError(error)
            k.WaitNamedPipeW(name, 100)
            if error == 2:
                time.sleep(0.025)

    def _transfer(self, function, buffer, length: int) -> tuple[int, int]:
        """Run one overlapped operation; return (error, transferred)."""
        with self._lock:
            if self._closed:
                raise DisconnectedError("Named pipe closed")
            self._in_flight += 1
        k = self._dll
        event = k.CreateEventW(None, True, False, None)
        try:
            if not event:
                raise ctypes.WinError(ctypes.get_last_error())
            overlapped = self._overlapped(hEvent=event)
            count = self._wintypes.DWORD()
            error = 0
            if not function(self._handle, buffer, length, None, ctypes.byref(overlapped)):
                error = ctypes.get_last_error()
                if error != 997:  # ERROR_IO_PENDING
                    return error, 0
            # Waiting here keeps `buffer` and `overlapped` alive until the
            # kernel has finished with them, including after cancellation.
            if not k.GetOverlappedResult(self._handle, ctypes.byref(overlapped),
                                         ctypes.byref(count), True):
                return ctypes.get_last_error(), count.value
            return 0, count.value
        finally:
            if event:
                k.CloseHandle(event)
            with self._lock:
                self._in_flight -= 1
                self._idle.notify_all()

    def read(self, size: int) -> bytes:
        buffer = ctypes.create_string_buffer(min(size, 65536))
        try:
            error, count = self._transfer(self._dll.ReadFile, buffer, len(buffer))
        except DisconnectedError:
            return b""
        if error in self._ABORTED:
            return b""
        if error and error != 234:  # ERROR_MORE_DATA still delivered `count`
            raise ctypes.WinError(error)
        return buffer.raw[:count]

    def write(self, data: bytes | memoryview) -> int:
        part = bytes(data[:65536])
        buffer = ctypes.create_string_buffer(part, len(part))
        error, count = self._transfer(self._dll.WriteFile, buffer, len(part))
        if error in self._ABORTED:
            raise DisconnectedError("Named pipe closed")
        if error:
            raise ctypes.WinError(error)
        return count

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        if not self._close_when_idle(time.monotonic() + 1):
            # Never close/reuse a handle while an operation still owns it.
            threading.Thread(target=self._close_when_idle, args=(None,),
                             name="nativehtmlkit-pipe-close", daemon=True).start()

    def _close_when_idle(self, deadline):
        while True:
            with self._lock:
                if not self._in_flight:
                    self._dll.CloseHandle(self._handle)
                    return True
            # Repeat: an operation may be issued just after a cancellation.
            self._dll.CancelIoEx(self._handle, None)
            with self._idle:
                if self._in_flight:
                    self._idle.wait(0.01)
            if deadline is not None and time.monotonic() >= deadline:
                return False


def connect_stream(endpoint: str, timeout: float = 15.0):
    if os.name == "nt":
        return NamedPipeStream(endpoint, timeout)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(endpoint)
        sock.settimeout(None)
        return SocketStream(sock)
    except BaseException:
        sock.close()
        raise


def read_exact(stream, length: int, *, clean_eof: bool = False) -> bytes | None:
    chunks = bytearray()
    while len(chunks) < length:
        piece = stream.read(length - len(chunks))
        if not piece:
            if clean_eof and not chunks:
                return None
            raise DisconnectedError("Connection closed inside a frame")
        chunks.extend(piece)
    return bytes(chunks)


def _unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ProtocolError(f"Duplicate JSON member: {key}")
        result[key] = value
    return result


def _check_keys(value) -> None:
    """JSON object keys must be strings: json.dumps would turn {1: .., "1": ..} into duplicates."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str):
                    raise LocalRequestError(f"JSON object keys must be strings, got {type(key).__name__}")
                stack.append(child)
        elif isinstance(item, (list, tuple)):
            stack.extend(item)


def encode_frame(value: dict) -> bytes:
    """Encode an OUTGOING message. Failures are the caller's own (LocalRequestError): nothing is sent."""
    _check_keys(value)
    try:
        body = json.dumps(value, ensure_ascii=False, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise LocalRequestError(f"Request is not encodable as JSON ({type(exc).__name__})") from exc
    if not body or len(body) > MAX_FRAME_BYTES:
        raise LocalRequestError(f"Request exceeds the {MAX_FRAME_BYTES}-byte frame limit")
    return struct.pack(">I", len(body)) + body


def read_frame(stream) -> dict | None:
    header = read_exact(stream, 4, clean_eof=True)
    if header is None:
        return None
    length, = struct.unpack(">I", header)
    if length == 0 or length > MAX_FRAME_BYTES:
        raise ProtocolError("Invalid frame size")
    body = read_exact(stream, length)
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object,
                           parse_constant=lambda _: (_ for _ in ()).throw(ProtocolError("Non-finite number")))
    except (UnicodeError, ValueError, RecursionError) as error:
        raise ProtocolError("Invalid UTF-8 JSON") from error
    if not isinstance(value, dict) or value.get("jsonrpc") != "2.0":
        raise ProtocolError("Expected a JSON-RPC 2.0 object")
    return value


def write_all(stream, frame: bytes) -> None:
    remaining = memoryview(frame)
    while remaining:
        size = stream.write(remaining)
        if not size:
            raise DisconnectedError("Connection closed while writing")
        remaining = remaining[size:]


def use_utf8_stdio() -> None:
    """Write UTF-8 to stdout/stderr when they are the host's log pipes.

    On Windows, Python encodes a piped stdout with the ANSI code page, so
    printing text such as "→" or "😀" raised UnicodeEncodeError. The host
    decodes backend output as UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="backslashreplace")


_LOOP_WARNED = False


def _warn_if_event_loop(method: str) -> None:
    """A blocking call on a running asyncio loop stalls every task on it."""
    global _LOOP_WARNED
    try:
        import asyncio
        asyncio.get_running_loop()
    except RuntimeError:
        return
    diagnostics.record("rpc.sync_call_on_event_loop", level="WARN", method=method)
    if not _LOOP_WARNED:
        _LOOP_WARNED = True
        import warnings
        warnings.warn("Blocking NativeHTMLKit RPC on a running asyncio event loop; "
                      "use AsyncRpcClient / Application.async_adapter() or asyncio.to_thread()",
                      RuntimeWarning, stacklevel=3)


class RpcClient:
    def __init__(self, stream, *, workers: int = 4, ordered_notifications: bool = False):
        self._stream = stream
        self._lock = threading.RLock()
        self._pending: dict[str, concurrent.futures.Future] = {}
        self._request_meta: dict[str, tuple[str, float]] = {}
        self._next_id = 0
        self._closed = threading.Event()
        self.shutdown_requested = threading.Event()
        self._handlers: dict[str, Callable[[dict], Any]] = {}
        self._notifications: dict[str, Callable[[dict], None]] = {}
        self._outgoing = queue.Queue(maxsize=256)
        self._callbacks = queue.Queue(maxsize=128)
        # Optional application-event ordering must not serialize lifecycle
        # policy requests behind a user callback waiting for a native dialog.
        # The default client retains its qualified callback-pool behavior.
        self._ordered_notifications = queue.Queue(maxsize=128) if ordered_notifications else None
        self._queued_bytes = 0
        self._event_seq = 0
        self.dropped_notifications = 0
        self._failure: BaseException | None = None
        self._quit_requested = False
        self.on_request("window.before_close", lambda _: {"allow": True})
        self.on_request("app.before_quit", lambda _: {"allow": True})
        self.on_request("app.shutdown", self._shutdown)
        self.on_notification("app.shutdown", self._shutdown)
        self._io_threads = [
            threading.Thread(target=self._reader, name="nativehtmlkit-receiver", daemon=True),
            threading.Thread(target=self._writer, name="nativehtmlkit-writer", daemon=True),
        ]
        self._threads = self._io_threads + [threading.Thread(target=self._callback_worker, name=f"nativehtmlkit-callback-{i}", daemon=True)
             for i in range(workers)]
        if self._ordered_notifications is not None:
            self._threads.append(threading.Thread(target=self._callback_worker,
                args=(self._ordered_notifications,), name="nativehtmlkit-application-events", daemon=True))
        for thread in self._threads:
            thread.start()

    @classmethod
    def from_environment(cls, *, workers: int = 4, ordered_notifications: bool = False):
        use_utf8_stdio()
        # Wire v1 uses legacy names. Credentials must not survive *failed* auth
        # either: children spawned by an error handler must not inherit the token.
        wire = ("UI4ME_ENDPOINT", "UI4ME_TOKEN", "UI4ME_APP_ID", "UI4ME_PROTOCOL_VERSION")
        client = None
        try:
            endpoint, token = os.environ["UI4ME_ENDPOINT"], os.environ["UI4ME_TOKEN"]
            if not _TOKEN.fullmatch(token):
                # Never echo the value: it may be a real credential in the wrong shape.
                raise ProtocolError("UI4ME_TOKEN is not a 64-character hex launch credential")
            client = cls(connect_stream(endpoint), workers=workers,
                         ordered_notifications=ordered_notifications)
            client.hello = client.call("host.hello", {
                "token": token, "protocol_version": 1,
                "client": {"name": "nativehtmlkit-python", "version": CLIENT_VERSION},
            })
            if client.hello.get("protocol_version") != 1:
                raise ProtocolError("NativeHTMLKit Core did not negotiate protocol v1")
            diagnostics.record("host.authenticated", protocol_version=1)
            return client
        except BaseException:
            if client is not None:
                client.close()
            raise
        finally:
            for name in wire:
                os.environ.pop(name, None)

    def _shutdown(self, _):
        return {"ok": True}

    def on_request(self, method: str, callback: Callable[[dict], Any]) -> None:
        self._handlers[method] = callback

    def on_notification(self, method: str, callback: Callable[[dict], None]) -> None:
        self._notifications[method] = callback

    def _enqueue(self, message: dict) -> None:
        frame = encode_frame(message)
        with self._lock:
            if self._closed.is_set():
                raise DisconnectedError("Connection is closed") from self._failure
            if self._queued_bytes + len(frame) > MAX_QUEUED_BYTES:
                raise ClientBusyError("Outgoing buffer is full", operation=message.get("method"))
            try:
                self._outgoing.put_nowait(frame)
            except queue.Full:
                raise ClientBusyError("Outgoing queue is full", operation=message.get("method")) from None
            self._queued_bytes += len(frame)

    def call_async(self, method: str, params: dict | None = None) -> concurrent.futures.Future:
        """Send a request; return a Future that is completed off the transport reader.

        ``future.cancel()`` asks the host to cancel (advisory). Each completion runs on its own
        short-lived ``nativehtmlkit-completion`` thread, so done-callbacks may call synchronous
        RPCs or wait on other ``call_async`` futures without blocking other completions.
        """
        raw = self._submit(method, params)
        user: concurrent.futures.Future = concurrent.futures.Future()
        user.request_id, user.operation = raw.request_id, raw.operation

        def forward_cancel(done):
            if done.cancelled():
                raw.cancel()
        user.add_done_callback(forward_cancel)
        raw.add_done_callback(lambda done: self._complete(user, done))
        return user

    def _complete(self, user: concurrent.futures.Future, raw: concurrent.futures.Future) -> None:
        if user.done():
            return
        try:
            threading.Thread(target=self._deliver, args=(user, raw), name="nativehtmlkit-completion",
                             daemon=True).start()
        except RuntimeError:  # interpreter shutting down: no new threads
            self._deliver(user, raw)

    @staticmethod
    def _deliver(user: concurrent.futures.Future, raw: concurrent.futures.Future) -> None:
        """Copy the transport outcome into the application's future (runs its done-callbacks)."""
        if user.done():
            return
        try:
            if raw.cancelled():
                user.cancel()
            elif raw.exception() is not None:
                user.set_exception(raw.exception())
            else:
                user.set_result(raw.result())
        except concurrent.futures.InvalidStateError:
            pass  # cancelled by the application meanwhile
        except BaseException as error:  # a failing done-callback is reported, never propagated
            diagnostics.record("callback.failed", level="ERROR", exception_type=type(error).__name__,
                               owner="future")

    def _submit(self, method: str, params: dict | None = None) -> concurrent.futures.Future:
        """Internal: the transport future (completed on the reader thread; SDK use only)."""
        future = concurrent.futures.Future()
        with self._lock:
            if self._closed.is_set():
                raise DisconnectedError("Connection is closed", operation=method) from self._failure
            if len(self._pending) >= MAX_PENDING:
                raise ClientBusyError("Too many outstanding requests", operation=method)
            self._next_id += 1
            request_id = f"py-{self._next_id}"
            self._pending[request_id] = future
            self._request_meta[request_id] = (method, time.monotonic())
            pending = len(self._pending)
        command = (params or {}).get("command") if method == "document.command" else None
        op = command.get("op") if isinstance(command, dict) else None
        diagnostics.record("rpc.started", level="TRACE", request_id=request_id, method=method,
                           op=op if isinstance(op, str) else None, cause_seq=CAUSE.get(), pending=pending)
        future.request_id = request_id
        future.operation = method
        try:
            self._enqueue({"jsonrpc": "2.0", "id": request_id,
                           "method": method, "params": params or {}})
        except BaseException:
            with self._lock:
                self._pending.pop(request_id, None)
                self._request_meta.pop(request_id, None)
            raise
        def cancelled(done):
            if done.cancelled():
                with self._lock:
                    self._pending.pop(request_id, None)
                    self._request_meta.pop(request_id, None)
                diagnostics.record("rpc.cancel_requested", level="WARN", method=method, request_id=request_id)
                try:
                    self.notify("request.cancel", {"id": request_id})
                except (DisconnectedError, RpcError):
                    pass
        future.add_done_callback(cancelled)
        return future

    def call(self, method: str, params: dict | None = None, *, timeout=_DEFAULT_TIMEOUT):
        # User-operated native dialogs have no implicit deadline. An explicit
        # caller timeout still requests cancellation and leaves outcome advisory.
        if timeout is _DEFAULT_TIMEOUT:
            timeout = None if method.startswith("dialog.") else 15.0
        _warn_if_event_loop(method)
        future = self._submit(method, params)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError as error:
            # Outcome may be unknown; this is not a rollback. If the reply won
            # the race against the deadline, its known outcome is returned.
            if not future.cancel() and future.done() and not future.cancelled():
                return future.result(0)
            diagnostics.record("rpc.timeout", level="ERROR", method=method, request_id=future.request_id)
            raise RpcTimeoutError("RPC deadline exceeded; remote outcome may be unknown",
                                  operation=method, request_id=future.request_id) from error

    def notify(self, method: str, params: dict | None = None) -> None:
        self._enqueue({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def _writer(self):
        try:
            while not self._closed.is_set():
                try:
                    frame = self._outgoing.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    write_all(self._stream, frame)
                finally:
                    with self._lock:
                        self._queued_bytes -= len(frame)
        except BaseException as error:
            self._fail(error)

    def _reader(self):
        try:
            while not self._closed.is_set():
                message = read_frame(self._stream)
                if message is None:
                    raise DisconnectedError("Host disconnected")
                if "method" in message:
                    if not isinstance(message["method"], str) or not isinstance(message.get("params", {}), dict):
                        raise ProtocolError("Invalid host request")
                    if "id" in message and not isinstance(message["id"], str):
                        raise ProtocolError("Request IDs must be strings")
                    if message["method"] == "app.shutdown":
                        # Orderly shutdown is known on receipt, even if every worker is
                        # busy and the host closes the connection right after it.
                        self.shutdown_requested.set()
                    callbacks = self._callbacks
                    if (self._ordered_notifications is not None and "id" not in message
                            and message["method"] != "app.shutdown"):
                        callbacks = self._ordered_notifications
                    try:
                        callbacks.put_nowait(message)
                    except queue.Full:
                        if "id" in message:
                            try:
                                self._enqueue({"jsonrpc": "2.0", "id": message["id"],
                                               "error": {"code": -32005, "message": "Callback queue is full"}})
                            except ClientBusyError:
                                self.dropped_notifications += 1
                                diagnostics.record("rpc.host_request_unanswered", level="ERROR",
                                                   method=message["method"])
                        else:
                            self.dropped_notifications += 1
                            diagnostics.record("rpc.notification_dropped", level="WARN", total=self.dropped_notifications)
                else:
                    request_id = message.get("id")
                    if not isinstance(request_id, str) or (("result" in message) == ("error" in message)):
                        raise ProtocolError("Invalid response")
                    with self._lock:
                        future = self._pending.pop(request_id, None)
                        meta = self._request_meta.pop(request_id, None)
                    if meta:
                        error_code = message["error"].get("code") if isinstance(message.get("error"), dict) else None
                        diagnostics.record("rpc.completed", level="TRACE", request_id=request_id,
                                           method=meta[0], duration_ms=int((time.monotonic()-meta[1])*1000),
                                           failed="error" in message,
                                           error_code=error_code if isinstance(error_code, int) else None)
                    if future is None or future.done():
                        # Late response to a cancelled request, or an ID never issued.
                        diagnostics.record("rpc.unmatched_response", level="DEBUG", request_id=request_id,
                                           cancelled=bool(future is not None and future.cancelled()))
                        continue
                    if "error" in message:
                        e = message["error"]
                        if (not isinstance(e, dict) or not isinstance(e.get("code"), int)
                                or isinstance(e.get("code"), bool) or not isinstance(e.get("message"), str)):
                            if not future.done():
                                future.set_exception(ProtocolError("Invalid RPC error", operation=meta[0] if meta else None,
                                                                   request_id=request_id))
                            raise ProtocolError("Invalid RPC error")
                        try:
                            future.set_exception(RpcError(e["code"], e["message"], e.get("data"),
                                                          operation=meta[0] if meta else None,
                                                          request_id=request_id))
                        except concurrent.futures.InvalidStateError:
                            pass
                    else:
                        try:
                            future.set_result(message["result"])
                        except concurrent.futures.InvalidStateError:
                            pass
        except BaseException as error:
            self._fail(error)

    def _callback_worker(self, callbacks=None):
        callbacks = self._callbacks if callbacks is None else callbacks
        while not self._closed.is_set():
            try:
                message = callbacks.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                if not self._dispatch(message):
                    return
            except BaseException as error:  # SystemExit etc. from user code: report, keep serving
                diagnostics.record("callback.failed", level="ERROR", exception_type=type(error).__name__,
                                   method=message.get("method"))
                print(f"NativeHTMLKit callback raised {type(error).__name__}; event delivery continues "
                      "(use Application.close()/request_quit() to stop)", file=sys.stderr, flush=True)
            finally:
                callbacks.task_done()

    def wait_for_notifications(self, timeout: float) -> bool:
        """Wait until ordered notifications already received have been handled.

        The host sends a window's final ``closed`` event before ``app.shutdown``,
        but shutdown is handled outside the ordered queue. Returns False on
        timeout (for example a callback still waiting for a native dialog).
        """
        if self._ordered_notifications is None:
            return True
        deadline = time.monotonic() + timeout
        while self._ordered_notifications.unfinished_tasks:
            if self._closed.is_set() or time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True

    def _dispatch(self, message) -> bool:
        """Handle one host message; False when the connection is gone."""
        method, params = message["method"], message.get("params", {})
        if "id" not in message:
            with self._lock:
                self._event_seq += 1
                seq = self._event_seq
            event = params.get("event") if method == "document.event" else None
            diagnostics.record("host.notification", level="TRACE", method=method, event_seq=seq,
                               window_id=params.get("window_id"), document_id=params.get("document_id"),
                               event_type=(event.get("type") if isinstance(event, dict) else params.get("type")),
                               element=event.get("element") if isinstance(event, dict) else None)
            callback = self._notifications.get(method)
            if callback:
                token = CAUSE.set(seq)
                started = time.monotonic()
                diagnostics.record("callback.started", level="TRACE", method=method, event_seq=seq)
                try:
                    callback(params)
                    diagnostics.record("callback.completed", level="TRACE", method=method, event_seq=seq,
                                       duration_ms=int((time.monotonic() - started) * 1000))
                except Exception as error:
                    diagnostics.record("callback.failed", level="ERROR", exception_type=type(error).__name__,
                                       method=method, event_seq=seq)
                    print(f"Notification handler failed: {type(error).__name__}: {error}", file=sys.stderr, flush=True)
                finally:
                    CAUSE.reset(token)
            if method == "app.shutdown":
                self.shutdown_requested.set()
            return True
        fatal: BaseException | None = None
        try:
            callback = self._handlers.get(method)
            if callback is None:
                raise RpcError(-32601, f"Unknown method: {method}")
            result = callback(params)
            response = {"jsonrpc": "2.0", "id": message["id"], "result": result}
        except RpcError as error:
            response = {"jsonrpc": "2.0", "id": message["id"], "error": {
                "code": error.code, "message": error.message, "data": error.data}}
        except BaseException as error:  # a host request is ALWAYS answered (never exception text)
            diagnostics.record("callback.failed", level="ERROR", exception_type=type(error).__name__, method=method)
            response = {"jsonrpc": "2.0", "id": message["id"], "error": {
                "code": -32603, "message": f"Callback failed: {type(error).__name__}"}}
            if isinstance(error, (SystemExit, KeyboardInterrupt)):
                fatal = error
                if method == "app.before_quit":
                    # The application wants to exit: allow the quit already in progress (a -32603
                    # would veto it and a new quit request would loop).
                    response = {"jsonrpc": "2.0", "id": message["id"], "result": {"allow": True}}
        try:
            encode_frame(response)
        except LocalRequestError as error:
            diagnostics.record("callback.result_unencodable", level="ERROR", method=method)
            response = {"jsonrpc": "2.0", "id": message["id"], "error": {
                "code": -32603, "message": "Callback result is not JSON-serializable"}}
        deadline = time.monotonic() + 2.0
        while True:
            try:
                self._enqueue(response)
                break
            except ClientBusyError:
                # Transient back-pressure: retry briefly; never retire the worker for it.
                if self._closed.is_set() or time.monotonic() >= deadline:
                    diagnostics.record("rpc.host_request_unanswered", level="ERROR", method=method)
                    break
                time.sleep(0.01)
            except (DisconnectedError, RpcError):
                break
        if method == "app.shutdown":
            self.shutdown_requested.set()
        if fatal is not None and method != "app.before_quit":
            # Controlled effect of SystemExit/KeyboardInterrupt in a host-request handler: the request
            # was answered above; ask the host ONCE per client for an orderly quit.
            with self._lock:
                first, self._quit_requested = not self._quit_requested, True
            print(f"NativeHTMLKit: {type(fatal).__name__} in a {method} handler"
                  + ("; requesting application quit" if first else ""), file=sys.stderr, flush=True)
            if first:
                try:
                    self._submit("app.request_quit")
                except NativeHTMLKitError:
                    pass
        return not self._closed.is_set()

    def _fail(self, error: BaseException):
        with self._lock:
            if self._closed.is_set():
                return
            self._failure = error
            self._closed.set()
            pending, self._pending = self._pending, {}
            meta, self._request_meta = self._request_meta, {}
        local = isinstance(error, _ClientClosed)
        diagnostics.record("transport.closed" if local else "transport.disconnected",
                           level="DEBUG" if local else "ERROR",
                           exception_type=type(error).__name__, pending=len(pending))
        self._stream.close()
        reason = "Client closed" if local else f"Host connection lost ({type(error).__name__})"
        for request_id, future in pending.items():
            if not future.done():
                failure = DisconnectedError(
                    f"{reason}; outcome of {meta.get(request_id, ('request',))[0]} is unknown",
                    operation=meta.get(request_id, (None,))[0], request_id=request_id,
                    pending_failed=len(pending))
                failure.__cause__ = error
                try:
                    future.set_exception(failure)
                except concurrent.futures.InvalidStateError:
                    pass

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def wait(self, timeout: float | None = None) -> bool:
        return self._closed.wait(timeout)

    def flush(self, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self._queued_bytes == 0:
                    return
            if self._closed.wait(0.01):
                return
        raise TimeoutError("Outgoing messages did not drain")

    @property
    def closed_locally(self) -> bool:
        """True when :meth:`close` (not the host or a transport error) ended the connection."""
        return isinstance(self._failure, _ClientClosed)

    def close(self):
        """Close the connection. I/O threads are joined (1 s each); callback workers get one
        shared bounded join (0.5 s): a worker still blocked in user code is a daemon thread,
        left running and recorded as ``callback.worker_abandoned``, never awaited forever."""
        self._fail(_ClientClosed("Client closed"))
        current = threading.current_thread()
        for thread in self._io_threads:
            if thread is not current:
                thread.join(timeout=1.0)
        deadline = time.monotonic() + 0.5
        abandoned = []
        for thread in self._threads:
            if thread in self._io_threads or thread is current:
                continue
            thread.join(timeout=max(0.0, deadline - time.monotonic()))
            if thread.is_alive():
                abandoned.append(thread.name)
        if abandoned:
            diagnostics.record("callback.worker_abandoned", level="WARN", threads=len(abandoned))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
