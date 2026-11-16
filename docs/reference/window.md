# `Window`

```python
from nativehtmlkit import Window   # type only; windows come from Application
```

A `Window` is a handle to one native top-level window. Create it with
[`Application.create_window`, `open_html` or `open_file`](application.md#windows). Each window
holds at most one [`Document`](document.md) at a time.

## Attributes

| Attribute | Type | Meaning |
|---|---|---|
| `app` | `Application` | The owning application. |
| `id` | `str` | Opaque host ID such as `"w1"`. Never reused within a session. |
| `document` | `Document \| None` | The current document, `None` before the first load or after `unload()`. |
| `closed` | `bool` | `True` once the host reported the window closed or the application shut down. |

## Stale-handle semantics

When the window closes (its `closed` window event, or `app.shutdown` for the last window) the SDK
sets `closed = True` and retires its document. Every later call on the window, its document or
its nodes raises [`StaleDocumentError`](errors.md#staledocumenterror) locally, without contacting
the host. Check `window.closed` or catch the error in code that may outlive a window (threads,
timers, futures).

## Loading documents

### `load_html`

```python
window.load_html(html: str, *, asset_root: str | Path | None = None) -> Document
```

Replace the window's document with `html` (at most 1 MiB, else `RpcError` -32005). `asset_root`
is the directory for relative URLs; it is resolved to an absolute path. The previous document is
retired only after the new one loaded successfully: a failed load leaves the old document live.
Returns the new [`Document`](document.md), also available as `window.document`.

### `load_file`

```python
window.load_file(path: str | Path, *, asset_root: str | Path | None = None) -> Document
```

Load a UTF-8 HTML file of at most 1 MiB. The path is resolved to an absolute path; `asset_root`
defaults to the file's directory, so `<link href="style.css">` and `<img src="logo.png">` next to
the file work. A missing file fails with `RpcError` -32002.

Both raise `StaleDocumentError` if the window is closed and `ApplicationShutdownError` once the
application is shutting down. The host admits at most 16 live documents.

```python
document = window.load_file(Path(__file__).with_name("index.html"))
document.set_text("status", "Loaded")
```

## Window state

### `state`

`window.state() -> dict` returns the window description (`window.get`):

| Member | Meaning |
|---|---|
| `window_id`, `title`, `width`, `height`, `visible` | As requested, logical pixels |
| `native` | `False` in headless mode |
| `scale_factor` | Display scale |
| `physical_size` | Actual size in physical pixels, or `None` |
| `requested` | `{"visible", "resizable", "decorations", "size_constraints": {"min_width", "min_height", "max_width", "max_height"}}` |
| `observed` | `{"focused", "minimized", "maximized", "fullscreen", "resizable", "decorations", "visible", "theme", "position"}`; each `None` when the platform cannot report it (always in headless mode) |
| `closing` | `True` while a close is in progress |

`app.rpc.call("window.list")` returns the same description for every open window.

### `set`

```python
window.set(**properties) -> dict
```

Change window properties and return the updated description. Accepted keywords (all optional):

| Keyword | Type |
|---|---|
| `title` | `str` |
| `width`, `height` | `int`, logical pixels |
| `visible`, `resizable`, `decorations` | `bool` |
| `minimized`, `maximized`, `fullscreen` | `bool` |
| `focus` | `bool` (`True` asks for focus) |
| `x`, `y` | `int`, together; screen position |
| `min_width` + `min_height`, `max_width` + `max_height` | `int` pairs; `None` removes the constraint |

Unknown keywords, and `x` without `y`, fail with `RpcError` -32602. Platform limits are reported as
`RpcError` -32001. On Linux the Wayland compositor owns placement and focus: `x`/`y` and
`minimized=False` are always refused there, and `focus=True` and `visible` are refused for an
existing native window. On Windows all members are applied. The `observed` members of the returned
description show what the platform actually did.

```python
window.set(title="Report — saved", width=1024, height=720)
window.set(min_width=480, min_height=320)
window.set(maximized=True)
```

### `request_attention`

```python
window.request_attention(kind: str | None = "informational") -> dict
```

Ask the desktop to draw attention to the window: `"informational"`, `"critical"`, or `None` to
clear the request. Returns `{"requested": True, "kind", "presented": None, "policy"}`. Raises
`RpcError` -32001 in headless mode and where the window manager does not support it (Wayland cannot
clear a request).

## Closing

### `request_close`

`window.request_close() -> None`. Ask to close the window as if the user had. The host sends
`close_requested` (reason `backend_request`), asks the window's [`on_before_close`](#on_before_close)
policy, then closes the window (`closed` event). Closing the last window quits the application
(after [`on_before_quit`](application.md#on_before_quit)). Before `app.ready`, closing the last
usable window cancels start-up.

### `on_before_close`

```python
window.on_before_close(callback: Callable[[], bool]) -> None
```

Install a close policy for this window: `callback()` returns `True` to allow closing and `False`
to keep the window open (for example to show an "unsaved changes" banner). One policy per window;
a new call replaces it. Windows without a policy always close. The callback runs on an SDK worker
thread and must answer promptly (the host waits indefinitely); it may call the SDK. An exception
counts as deny.

```python
def allow_close() -> bool:
    if editor.dirty:
        window.document.add_class("unsaved-banner", "shown")
        return False
    return True
window.on_before_close(allow_close)
```

## Native file dialogs

```python
window.open_files(*, multiple=False, title=None, directory=None, filters=(), wait=True)
window.save_file(*, file_name=None, title=None, directory=None, filters=(), wait=True)
window.choose_folder(*, title=None, directory=None, wait=True)
```

Show a native dialog parented to this window. `filters` is a list of
`{"name": "Images", "extensions": ["png", "jpg"]}` (extensions without the dot). `directory` is
the start folder.

The result is a `dict`: `{"cancelled": bool, "paths": [str, ...]}`. `paths` has one entry for
`save_file` and `choose_folder`, and one or more for `open_files(multiple=True)`; it is empty when
the user cancelled.

- `wait=True` (default) blocks until the user answers. There is no timeout.
- `wait=False` returns a `concurrent.futures.Future` at once; read it in a done-callback.
  `future.cancel()` asks the host to close the native dialog.

Errors: `RpcError` -32001 in headless mode and without a desktop dialog service (on Linux the
desktop portal), -32005 if this window already shows a native dialog or the host's service limit is
reached, `StaleDocumentError` for a closed window. With `wait=False` the error is set on the future.

```python
def done(future):
    try:
        result = future.result()
    except RpcError as error:
        print("no dialog:", error.code)
        return
    if not result["cancelled"]:
        window.document.set_text("chosen", result["paths"][0])

window.open_files(title="Choose an image", filters=[{"name": "Images", "extensions": ["png", "jpg"]}],
                  wait=False).add_done_callback(done)
```

A blocking (`wait=True`) dialog inside an event callback holds up later document and window events
until it closes. Prefer `wait=False` there. See the [file dialogs guide](../guides/file-dialogs.md).
