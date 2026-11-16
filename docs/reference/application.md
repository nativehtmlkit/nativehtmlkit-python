# `Application`

```python
from nativehtmlkit import Application
```

One `Application` is one connection to one NativeHTMLKit Core host. The host owns the native
windows, rendering and the event loop; the `Application` object owns the Python side: windows,
documents, callbacks and lifecycle hooks. Everything on this page is in `nativehtmlkit` 0.1.2
(bundled Core 1.0.3, wire protocol v1).

- [Creating an application](#creating-an-application): `start`, `from_environment`, the context manager
- [Windows](#windows): `create_window`, `open_html`, `open_file`
- [Running and stopping](#running-and-stopping): `ready`, `run`, `request_quit`, `close`
- [Lifecycle hooks](#lifecycle-hooks): `on_window_event`, `on_before_quit`, `on_shutdown`
- [Desktop services](#desktop-services): clipboard, `open_external`, `reveal_file`, preferences
- [Host information](#host-information): `capabilities`, `host_diagnostics`
- [asyncio](#asyncio): `async_adapter`
- [Attributes](#attributes)

## Creating an application

### `Application.start(...)` (classmethod)

```python
Application.start(*, name=None, app_id=None, version=None, icon=None, instance="single",
                  startup_timeout_ms=30_000, shutdown_timeout_ms=5_000, max_windows=16) -> Application
```

The normal entry point for `uv run app.py` and `uv run -m package.app`.

The call has **two roles**:

1. **Launcher** (the process you started). It validates the options, writes a private temporary
   manifest naming the same interpreter and command line, starts the bundled native host and relays
   the backend's `print()` output and errors to your console. When the host exits, this process
   exits with the host's status: `start()` **never returns** here (it raises `SystemExit`).
2. **Backend** (the same script, started again by the host). The host provided a connection; the
   call validates the options, connects, removes the connection secret from `os.environ` and
   **returns** the `Application`.

Everything before `Application.start()` therefore runs twice. Keep side effects (files, network,
`print`) after it and guard the entry point with `if __name__ == "__main__":`.

| Parameter | Default | Meaning and accepted values |
|---|---|---|
| `name` | script file stem (or the last module component) | Application/window name. 1–128 characters, no control characters. |
| `app_id` | `local.nativehtmlkit.<name-slug>.h<hash>` derived from the script path (or module and working directory) | Reverse-DNS identity, e.g. `org.example.Notes`: ASCII, at most 128 bytes, at least two dot-separated components, each starting with a letter and containing letters, digits, `_` or `-`. It also names the per-application directories returned by the host's `desktop.paths`. |
| `version` | `None` | Optional version string, same rules as `name`. |
| `icon` | `None` | Path to an icon file. It must exist (`StartupError` otherwise). |
| `instance` | `"single"` | `"single"`: a second launch of the same app is handed to the running one; `"multiple"`: every launch is independent. |
| `startup_timeout_ms` | `30000` | 1000–300000. Time the host allows for connecting and reaching `app.ready`. |
| `shutdown_timeout_ms` | `5000` | 100–120000. Deadline for the backend to exit after `app.shutdown`. |
| `max_windows` | `16` | 1–64. Window limit enforced by the host (`window.create` then fails with `RpcError` -32005). |

Raises:

- `ValueError`: an option is out of range (raised in both roles, before anything starts).
- `StartupError`: started from an interactive interpreter, `python -c` or standard input; no native
  host found (`NATIVEHTMLKIT_HOST_BINARY` missing file, wheel without host); the icon does not
  exist; the host could not be executed; an incomplete or recursive host environment.
- `HostVerificationError` (a `FileNotFoundError`): the wheel's bundled host does not match the
  SHA-256 pinned in its `HOST-MANIFEST.json`.
- `SystemExit(status)`: in the launcher role, always, with the host's exit status.
- In the backend role, connection errors from [`from_environment`](#applicationfrom_environment-classmethod).

With `NATIVEHTMLKIT_TEST_MODE=1` the launcher adds the host's `--headless` flag (no native
windows; see [environment variables](environment-variables.md)).

```python
from nativehtmlkit import Application

def main() -> None:
    with Application.start(name="Notes", app_id="org.example.Notes") as app:
        app.open_html("<h1>Hello</h1>", title="Notes")
        app.run()

if __name__ == "__main__":
    main()
```

### `Application.from_environment()` (classmethod)

```python
Application.from_environment() -> Application
```

Connect to the host that launched **this** process. The host passes `UI4ME_ENDPOINT`,
`UI4ME_TOKEN`, `UI4ME_APP_ID` and `UI4ME_PROTOCOL_VERSION`; the call authenticates with
`host.hello`, requires protocol v1 and removes those four variables from `os.environ` (also when
it fails), so child processes never inherit the credential. Use it in a backend started from your
own manifest (`nativehtmlkit-python-host run --app app.toml`); `Application.start()` and
`uv run -m nativehtmlkit run` call it for you.

Raises `StartupError` when the endpoint or token variable is missing, `ProtocolError` for a token
that is not 64 hexadecimal characters or a host that did not negotiate protocol v1, `RpcError` if
the host refuses authentication, and `OSError` if the endpoint cannot be opened.

### Context manager

`with Application.start(...) as app:` returns the application and calls [`close()`](#close) on
exit. If the block raises (other than `SystemExit`/`KeyboardInterrupt`) the traceback is printed
**before** the connection closes, so it reaches your console through the host.

## Windows

### `create_window`

```python
app.create_window(*, title="NativeHTMLKit", width=900, height=600, visible=True, decorations=True,
                  min_width=None, min_height=None, max_width=None, max_height=None) -> Window
```

Create an empty native window and return its [`Window`](window.md). Sizes are logical (CSS)
pixels. Size constraints must be given in pairs (`min_width` with `min_height`, `max_width` with
`max_height`); a single value fails with `RpcError` -32602. `resizable` is not a creation option
here: call `window.set(resizable=False)` afterwards.

Raises `ApplicationShutdownError` once the host has begun shutting down, `RpcError` -32005 when the
window limit (`max_windows`) is reached or a quit decision is pending, and -32001 for options the
platform refuses (for example a hidden window on Wayland).

A window without a document shows a built-in placeholder; load a document right away (or use
`open_html` / `open_file`).

### `open_html`

```python
app.open_html(html: str, *, asset_root=None, **window_options) -> Window
```

`create_window(**window_options)` followed by `window.load_html(html, asset_root=asset_root)`.
`html` is at most 1 MiB (UTF-8); larger documents fail with `RpcError` -32005. `asset_root` is a
directory used to resolve relative URLs (images, stylesheets). If loading fails, the new window is
closed and the error re-raised.

### `open_file`

```python
app.open_file(path: str | Path, **window_options) -> Window
```

`create_window(**window_options)` followed by `window.load_file(path)`. The path is resolved to an
absolute path; relative resources resolve against the file's directory. A missing file fails with
`RpcError` -32002. `open_file` does not take `asset_root`; use `app.create_window(...)` and
`window.load_file(path, asset_root=...)` for that.

```python
from pathlib import Path
HERE = Path(__file__).resolve().parent
window = app.open_file(HERE / "index.html", title="Viewer", width=800, height=600)
```

## Running and stopping

### `ready`

`app.ready() -> None`. Tell the host that start-up is complete (`app.ready`). Called once by
`run()`; calling it again does nothing. Raises `RpcError` -32008 if no window exists yet. Until
the application is ready the host cancels start-up when the user closes any window or when the
last window is closed from Python.

### `run`

`app.run() -> None`. Announce readiness and block until the host shuts the application down.
Before it returns, events the host sent ahead of `app.shutdown` are delivered (for up to two
seconds), every window and document handle is retired, and the [`on_shutdown`](#on_shutdown)
callbacks run in the calling thread.

Returns normally after an orderly shutdown (the user closed the last window, `request_quit()` was
allowed) or after this process called `close()`. Raises `DisconnectedError` if the host
connection was lost instead. Calling `run()` again after it returned does nothing.

### `request_quit`

`app.request_quit() -> None`. Ask the host to quit. The host then asks [`on_before_quit`](#on_before_quit)
(reason `backend_request`); if that allows it, the host sends `app.shutdown` and `run()` returns.
Safe to call from callbacks and other threads. This is the orderly way to end an application.

### `close`

`app.close() -> None`. Retire every handle and close the connection immediately. `run()` then
returns, but for the host this is a lost backend connection: it records an application failure and
exits with status 1. Prefer `request_quit()`; `close()` is for tear-down after `run()` returned (the
context manager calls it) or for abandoning a session.

## Lifecycle hooks

### `on_window_event`

```python
app.on_window_event(callback: Callable[[dict], Any]) -> Callable[[], None]
```

Call `callback(params)` for every native window event of this application; returns a function that
unsubscribes. Several callbacks may be registered. `params` is
`{"window_id": "w2", "type": ..., "data": {...}}`:

| `type` | `data` |
|---|---|
| `close_requested` | `reason`: `"native_close"` (user) or `"backend_request"` (`Window.request_close`) |
| `closed` | `{}`. The SDK has already marked the window closed and retired its document. |
| `resized` | `physical_width`, `physical_height`, `scale_factor` |
| `scale_changed` | `scale_factor` |
| `focused` | `focused` (bool) |
| `key` | `key`, `state` (`"pressed"`/`"released"`), `repeat`, `physical_key` |

When closing the **last** window ends the application, no `closed` event is sent for it: the
host goes straight to `app.shutdown`, after which all handles are stale. Callbacks run on the
application event thread, in order; an exception is printed and does not stop other callbacks.

```python
def log(params):
    print(params["window_id"], params["type"], params.get("data"))
stop = app.on_window_event(log)
```

### `on_before_quit`

```python
app.on_before_quit(callback: Callable[[], bool]) -> None
```

Install the quit policy. Before the application quits (last window closed, `request_quit()`), the
host asks; `callback()` returns `True` to allow and `False` to keep running. Only one policy is
active; a new call replaces the previous one. Without a policy every quit is allowed.

The callback runs on an SDK worker thread, not the event thread, and must answer promptly: the host
waits for the answer without a deadline. It may call the SDK (for example to show a confirmation
`<dialog>`). An exception counts as **deny**; `SystemExit`/`KeyboardInterrupt` count as allow.

```python
def may_quit() -> bool:
    if unsaved_changes():
        document.show_dialog("confirm-quit")
        return False
    return True
app.on_before_quit(may_quit)
```

### `on_shutdown`

```python
app.on_shutdown(callback: Callable[[], Any]) -> None
```

Run `callback()` once the host has shut the application down, in the thread that called `run()`,
after the final events were delivered. Several callbacks run in registration order; one failing
callback does not skip the others. The host connection is shutting down at this point: save files
and stop your threads here, but do not call window or document methods.

Window-level close policies are on [`Window.on_before_close`](window.md#on_before_close).

## Desktop services

These call native services. In headless mode, and where the platform lacks the service, they raise
`RpcError` with code **-32001** (unsupported). Check `capabilities()["features"]` or catch the
error.

| Method | Returns | Notes |
|---|---|---|
| `app.clipboard_text() -> str` | Clipboard text | Text only. |
| `app.set_clipboard_text(text: str) -> None` | | At most 1 MiB. |
| `app.open_external(target, *, window=None) -> dict` | `{"accepted", "cancelled", "parent_forwarded", "presented"}` | `target`: an `http`/`https`/`mailto`/`file` URI or an absolute path; opened with the desktop's default application. `window` parents the request. `accepted` is not proof that an application appeared. Other URI schemes are refused with `RpcError` -32003; on Windows so are executable file types. Waits up to 60 s. |
| `app.reveal_file(path, *, window=None) -> dict` | same shape | Show a local file in the file manager. The path is resolved to an absolute path. |
| `app.desktop_preferences() -> dict` | `{"color_scheme", "reduced_motion", "high_contrast", "available", "source", "revision", "scope"}` | Values are `None` when the platform does not report them. Works headless (`available: False`, `source: "headless"`). |
| `app.on_desktop_preferences(callback)` | | `callback(preferences)` with the same object whenever the desktop preferences change. One callback; a new call replaces it. |

`open_external` and `reveal_file` raise `ValueError` for a window of another application and
`StaleDocumentError` for a closed window.

```python
from nativehtmlkit import RpcError
try:
    app.set_clipboard_text("copied")
except RpcError as error:
    if error.code != -32001:
        raise
    print("No clipboard in this session")
```

## Host information

### `capabilities`

`app.capabilities() -> dict`: the host's capability report (`host.capabilities`, schema 2). Useful
members: `headless`, `native`, `platform`, `max_windows`, `max_documents`, `limits`,
`css_profile`, and `features`, a map of feature name to
`{"implemented": bool, "available": True | False | None, "qualification": str, "scope": str}`
(`available: None` means "not observed yet"). Feature names include `clipboard_text`,
`file_dialogs`, `external_open`, `reveal_file`, `attention`, `native_preferences`, `ime`,
`accessibility`, `incoming_drop`, `window_constraints`, `window_focus`, `window_position` and
`printing`/`tray` (not implemented). Prefer `features` over the legacy top-level booleans.

```python
features = app.capabilities()["features"]
can_pick_files = features["file_dialogs"]["available"] is not False
```

### `host_diagnostics`

`app.host_diagnostics(*, timeout=5.0) -> dict`: the host's own counters (`host.diagnostics`):
`phase`, `windows`, `pending_jobs`, `pending_transfers`, `pid`, `backend_pid`, `containment`,
`logging` and `dropped_notifications` (window/document events the host dropped because this
process stopped reading). Allowed even while shutting down. See [diagnostics](diagnostics.md).

## asyncio

### `async_adapter`

`app.async_adapter(*, loop=None) -> AsyncApplication`. An asyncio facade over the same connection.
Create it inside the running loop (or pass `loop`). See [asyncio reference](asyncio.md).

## Attributes

| Attribute | Type | Meaning |
|---|---|---|
| `rpc` | [`RpcClient`](rpc.md) | The authenticated connection. `rpc.hello` holds the `host.hello` result (`protocol_version`, `host_version`, `app_id`, `capabilities`). |
| `host_dropped_notifications` | `int \| None` | Set by `run()` at shutdown from `host.diagnostics` (`None` if unavailable). |

`Application(rpc)` can be constructed around an existing `RpcClient`; applications normally use
`start()` or `from_environment()`.

## Threading summary

All methods may be called from any thread. Where your code is called:

| Callback | Thread |
|---|---|
| `Document.on`, `on_window_event`, `on_desktop_preferences` | the single application event thread, in event order |
| `on_before_quit`, `Window.on_before_close` | an SDK worker thread (independent of the event thread) |
| `Future` done-callbacks from `wait=False` / `rpc.call_async` | a short-lived completion thread per result |
| `on_shutdown` | the thread that called `run()` |

A callback that blocks (for example a `wait=True` file dialog) delays later events, but close/quit
decisions are still answered. See [events and callbacks](../guides/events-and-callbacks.md).
