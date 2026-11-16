# Errors

```python
from nativehtmlkit import (NativeHTMLKitError, RpcError, RpcTimeoutError, HostDisconnectedError,
                           DisconnectedError, HostProtocolError, ProtocolError, StaleDocumentError,
                           StartupError)
```

Every SDK error derives from `NativeHTMLKitError`. Catch it to handle "anything NativeHTMLKit"; catch
the subclasses to react precisely. Never parse `str(error)`: use the attributes.

## Hierarchy

```text
NativeHTMLKitError (Exception)
├── RpcError                          code = numeric wire error code
│   └── ClientBusyError               local back-pressure, nothing sent       (nativehtmlkit.client)
├── RpcTimeoutError (TimeoutError)    local deadline expired, outcome unknown
├── HostDisconnectedError (ConnectionError)
│   └── DisconnectedError             connection lost or closed, outcome unknown
├── HostProtocolError
│   └── ProtocolError                 the host broke wire v1 (fatal)
├── LocalRequestError (ValueError)    request not encodable / > 2 MiB, nothing sent (nativehtmlkit.errors)
├── StaleHandleError                                                         (nativehtmlkit.errors)
│   ├── StaleDocumentError (RuntimeError)   window/document/node no longer live
│   └── ApplicationShutdownError (RuntimeError)   shutdown began, no new windows/documents
├── StartupError (RuntimeError)       host could not be started or reached
├── HostVerificationError (FileNotFoundError)   bundled host fails its SHA-256 pin (nativehtmlkit.errors)
└── UnsupportedFeatureError                                                  (nativehtmlkit.errors)
```

Classes without a module note are exported by `nativehtmlkit`. `StaleDocumentError` and
`ApplicationShutdownError` share the base `StaleHandleError`; `StartupError` is in
`nativehtmlkit._bootstrap` and re-exported.

## Common attributes

| Attribute | Meaning |
|---|---|
| `classification` | Stable category string, e.g. `"NHK-HOST-RPC"`, `"NHK-HANDLE-STALE"` |
| `code` | Same as `classification`, except on `RpcError`, where it is the numeric wire code |
| `operation` | The RPC method involved, if any (e.g. `"document.command"`) |
| `request_id` | The SDK's wire request id, if any |
| `session_id` | The [diagnostics](diagnostics.md) session id of this process |
| `data` | Extra error data from the host (`RpcError`) |
| `retryable` | `False` for all current classes |
| `outcome_unknown` | `True` when the host may or may not have applied the operation (`RpcTimeoutError`, disconnects). The SDK never claims a rollback. |

| Class | `classification` |
|---|---|
| `RpcError` | `NHK-HOST-RPC` |
| `ClientBusyError` | `NHK-CLIENT-BUSY` (`code` -32005, `local=True`) |
| `RpcTimeoutError` | `NHK-TRANSPORT-TIMEOUT` |
| `HostDisconnectedError`, `DisconnectedError` | `NHK-HOST-DISCONNECTED` (plus `pending_failed`: requests failed by the same event) |
| `HostProtocolError`, `ProtocolError` | `NHK-PROTOCOL-MALFORMED` |
| `LocalRequestError` | `NHK-REQUEST-INVALID` |
| `StaleHandleError`, `StaleDocumentError` | `NHK-HANDLE-STALE` |
| `ApplicationShutdownError` | `NHK-APP-SHUTDOWN` |
| `StartupError` | `NHK-STARTUP` |
| `HostVerificationError` | `NHK-HOST-UNVERIFIED` |
| `UnsupportedFeatureError` | `NHK-FEATURE-UNSUPPORTED` |

## `RpcError`

`RpcError(code, message, data=None, *, operation=None, request_id=None)`; members `code` (int),
`message` (host text, for logs only), `data`, `local` (`False` for host errors) and `error_id`
(same as `classification`). Wire codes:

| Code | Name | Typical cause |
|---|---|---|
| -32600 | invalid request | malformed envelope |
| -32601 | method not found | unknown method |
| -32602 | invalid params | unknown element id, unknown member, bad argument |
| -32603 | internal | unexpected host failure |
| -32001 | unsupported | not available here: headless mode, no desktop service, platform policy (e.g. Wayland placement) |
| -32002 | unavailable | a service or file is missing at run time (e.g. `load_file` of a missing file) |
| -32003 | denied | policy refusal (e.g. `open_external` with an unsupported URI scheme) |
| -32004 | closed | window or document no longer exists in the host |
| -32005 | busy | a limit was reached (windows, 1 MiB HTML, bitmap budget, one dialog per window, pending requests) |
| -32006 | cancelled | request cancelled |
| -32007 | disconnected | |
| -32008 | invalid state | wrong lifecycle phase: `app.ready` without a window or most calls after shutdown began |
| -32009 | timeout | |
| -32010 | version mismatch | protocol version is not 1 |
| -32011 | unauthenticated | wrong or missing launch token |

Treat unknown codes as failures.

## `StaleDocumentError`

Raised **locally**, before anything is sent, when you use a `Window` that is closed, or a
`Document`/`Node` that was replaced, unloaded, closed or retired by shutdown. It is a
`RuntimeError`. (If the host itself receives a stale id, it answers `RpcError` -32004 instead.)

## Patterns

```python
from nativehtmlkit import NativeHTMLKitError, RpcError, StaleDocumentError

try:
    window.document.set_text("status", "Saved")
except StaleDocumentError:
    pass                         # the window was closed meanwhile; nothing to update
except RpcError as error:
    if error.code == -32602:
        print("No element with that id")
    else:
        raise
```

In background threads that update the UI, catch `NativeHTMLKitError` around each update and stop
the thread when it occurs: it covers stale handles, shutdown and disconnects.
