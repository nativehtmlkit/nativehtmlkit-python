# `RpcClient`: the host connection

```python
from nativehtmlkit import RpcClient
rpc = app.rpc
```

`RpcClient` is the authenticated, length-prefixed JSON-RPC connection to the Core host (Unix socket
on Linux, named pipe on Windows). `Application`, `Window` and `Document` are built on it. Use it
directly for Core v1 methods that have no convenience wrapper, such as `desktop.paths`,
`window.list` or `document.get`. Parameters and results are those of the public Core wire protocol
v1 (method list and JSON schemas ship with the Core release under `protocol/v1/`).

## Attributes

| Attribute | Meaning |
|---|---|
| `hello` | The `host.hello` result: `protocol_version`, `host_version`, `app_id`, `capabilities` (set by `from_environment`) |
| `closed` (property) | `True` once the connection ended |
| `closed_locally` (property) | `True` when `close()` ended it (not the host or a transport error) |
| `shutdown_requested` | `threading.Event`, set when the host announced `app.shutdown` |
| `dropped_notifications` | Notifications the SDK dropped because its callback queue (128) was full |

## Requests

### `call`

```python
rpc.call(method: str, params: dict | None = None, *, timeout=<default>) -> Any
```

Send a request and wait for the result. The default timeout is 15 s, and **none** for `dialog.*`
methods (a person is answering). An explicit `timeout=None` waits forever. On timeout the SDK asks
the host to cancel and raises `RpcTimeoutError`; the remote outcome is unknown. If the reply won
the race against the deadline, its result is returned.

Raises `RpcError` (host error, `code` is the numeric wire code), `ClientBusyError` (an `RpcError`
with `local=True`: more than 128 requests pending or the 8 MiB outgoing buffer is full; nothing was
sent), `LocalRequestError` (`ValueError`: the request is not JSON-encodable, has non-string keys or
exceeds the 2 MiB frame; nothing was sent), `DisconnectedError`, `RpcTimeoutError`.

```python
paths = app.rpc.call("desktop.paths")        # {"config", "data", "cache", "state", "runtime"}
for w in app.rpc.call("window.list"):
    print(w["window_id"], w["title"])
```

`desktop.paths` returns per-application directories named after the app id (XDG directories on
Linux, the AppData folders on Windows). The directories are not created for you.

### `call_async`

```python
rpc.call_async(method: str, params: dict | None = None) -> concurrent.futures.Future
```

Send a request and return a `Future`. Done-callbacks run on a short-lived `nativehtmlkit-completion`
thread per result, so they may call synchronous SDK methods. `future.cancel()` asks the host to
cancel (advisory).

```python
future = app.rpc.call_async("window.get", {"window_id": window.id})
future.add_done_callback(lambda f: print(f.result()["title"]))
```

### `notify`

`rpc.notify(method: str, params: dict | None = None) -> None`: send a notification (no reply), for
example `request.cancel`.

## Host-to-client messages

| Method | Meaning |
|---|---|
| `on_request(method, callback)` | Answer host **requests** (`window.before_close`, `app.before_quit`): `callback(params)` returns the result (`{"allow": bool}`). One handler per method. Prefer `Window.on_before_close` / `Application.on_before_quit`, which `Application` routes through these. |
| `on_notification(method, callback)` | Handle host **notifications**: `callback(params)`. One handler per method; `Application` already uses `document.event`, `document.error`, `window.event` and `app.shutdown`. Registering one of those replaces the SDK's own handler and breaks the object model; use it for others such as `app.activated` (a second launch of a single-instance app: `{"args", "cwd", "activation_token"}`). |

## Lifetime

| Method | Meaning |
|---|---|
| `wait(timeout=None) -> bool` | Wait until the connection closed |
| `flush(timeout=2.0)` | Wait until queued outgoing messages were written; `TimeoutError` otherwise |
| `wait_for_notifications(timeout) -> bool` | Wait until already received ordered notifications were handled |
| `close()` | Close the connection; pending requests fail with `DisconnectedError` |

Construction: `RpcClient(stream, *, workers=4, ordered_notifications=False)` and
`RpcClient.from_environment(*, workers=4, ordered_notifications=False)` are used by
`Application.from_environment()`; applications rarely construct a client themselves.

## Threads

The client runs a reader and a writer thread that never execute application code, four worker
threads for host requests (and `app.shutdown`), and, for an `Application`, one ordered
"application events" thread for notifications. A full callback queue drops further notifications
(counted in `dropped_notifications`) and answers further host requests with error -32005, which
the host treats as a denial. See [architecture](../ARCHITECTURE.md).
