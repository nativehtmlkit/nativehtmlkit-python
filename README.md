# NativeHTMLKit — Python SDK

An independent Python SDK (`import nativehtmlkit`) for the [NativeHTMLKit Core](https://github.com/nativehtmlkit/nativehtmlkit-core)
host: native HTML/CSS desktop windows, DOM/form/node operations, events, live bitmaps and desktop
services. **No browser, JavaScript, web server, PyO3 extension or Rust compiler** is needed by users of a
platform wheel: the wheel embeds one prebuilt, SHA-256-pinned Core host. Pure standard library; Python ≥ 3.10.

**Version 0.1.1** — released on [PyPI](https://pypi.org/project/nativehtmlkit/) and [GitHub Releases](https://github.com/nativehtmlkit/nativehtmlkit-python/releases/tag/v0.1.1); bundles NativeHTMLKit Core 1.0.3. Wire protocol v1 is the **stable** wire contract (1.0)
since Core 1.0.3. This SDK version relies on Core 1.0.3 behaviour (backend output relayed at every diagnostics
level, out-of-order `document.load` replies, notification backpressure counters); a host given through
`NATIVEHTMLKIT_HOST_BINARY` should be 1.0.3 or later. Qualification record:
[`docs/QUALIFICATION.md`](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/docs/QUALIFICATION.md). Releases: <https://github.com/nativehtmlkit/nativehtmlkit-python/releases>.

## Install

```bash
python -m pip install nativehtmlkit
```

Only two platform wheels are published (there is no source distribution on PyPI):

| Platform | Wheel tag | Requirement |
|---|---|---|
| Linux x86-64 | `manylinux_2_39_x86_64` | glibc ≥ 2.39 (e.g. Ubuntu 24.04+, Debian 13, Fedora 40+) and a desktop session (Wayland/X11) |
| Windows x64 | `win_amd64` | Windows 10/11 or Server 2022, interactive desktop |

CPython 3.10–3.14. On any other platform (macOS, ARM, 32-bit, older glibc) pip finds no compatible
distribution and reports that no matching distribution was found; nothing is built from source. A downloaded
release wheel installs offline with `python -m pip install --no-index ./nativehtmlkit-0.1.1-py3-none-<tag>.whl`.
`nativehtmlkit-python version` shows the bundled host, its SHA-256 and whether it matches the pinned manifest.

## Run an app

```python
from nativehtmlkit import Application

def main():
    with Application.start(name="Hello NativeHTMLKit") as app:
        window = app.open_html('<button id="hello">Hello</button><p id="status"></p>')
        window.document.on("click", lambda _: window.document.set_text("status", "Hi"), element="hello")
        app.run()

if __name__ == "__main__":
    main()
```

`python app.py` starts the native host, which re-runs the same command as its supervised backend
(**two processes: top-level code before `Application.start()` runs twice**; keep side effects inside `main`).
The host-first runner avoids that:

```bash
python -m nativehtmlkit run mypackage.app:main --name MyApp     # or: nativehtmlkit-python run ...
```

`main(app)` runs only in the backend; it creates windows and subscribes to events, then the runner calls
`app.run()`. It may be `async def`; it then runs under `asyncio.run()` and may `await app.async_adapter().run()`.

Installed commands: `nativehtmlkit-python` (runner, `doctor`, `version`, `support`), `nativehtmlkit-python-host`
(forwards to the bundled host, e.g. `nativehtmlkit-python-host run --app app.toml`), `nativehtmlkit-new`
(project scaffold) and `nativehtmlkit-skill` (agent skill installer). The SDK never installs a `nativehtmlkit`
executable: that name belongs to the Rust CLI.

Host resolution (every launch path: `Application.start()`, `run`, `doctor`, `nativehtmlkit-python-host`):
1. `NATIVEHTMLKIT_HOST_BINARY` — explicit development override, used as given (not verified);
2. the wheel's bundled host — **verified against the SHA-256 in its `HOST-MANIFEST.json` before every launch**;
   a missing/unreadable manifest or a mismatch raises `HostVerificationError` and nothing is executed;
3. only with `NATIVEHTMLKIT_ALLOW_PATH_HOST=1`: the first `nativehtmlkit-host` in an *absolute* `PATH` entry
   (never the current directory or a relative entry, also on Windows); unpinned, so a warning is printed on
   stderr and recorded. Without the opt-in there is no PATH fallback.

`version` prints SDK/protocol versions, the host path, its SHA-256 and whether it matches the manifest. The
verification hashes the file before it is started; an attacker who can rewrite files inside the installed
package between that check and the start is out of scope (they could equally replace the SDK's Python code).

## Public API (summary)

| Object | Purpose |
|---|---|
| `Application` | `start()`, `from_environment()`, `open_html()/open_file()/create_window()`, `run()`, `close()`, `request_quit()`, `on_window_event()`, `on_shutdown()`, `on_before_quit()`, `capabilities()`, clipboard and desktop services, `async_adapter()`, low-level `rpc` |
| `Window` | `load_html()/load_file()`, `set()/state()`, `request_close()`, `on_before_close()`, native dialogs `open_files()/save_file()/choose_folder()` (`wait=False` returns a cancellable future) |
| `Document` | generation-bound DOM API: text/value/checked/attributes/classes/HTML, `query()/query_nodes()/node()`, forms (`form_data`, `request_submit`, validity), focus/selection/editing, styles, scrolling, dialogs/popovers, `register_resources()`, `create_bitmap()`, `command(op, **fields)` for every Core op, `on(event, cb, element=...)` → unsubscribe function |
| `Node` | opaque node references (incl. elements without ids) and node mutations |
| `LiveBitmap` | bounded RGBA8 frames for `<img src="ui4me-bitmap://ID">` |
| `RpcClient` | low-level wire-v1 client (`call`, `call_async` → `concurrent.futures.Future`, `notify`, `on_request`, `on_notification`) |
| `AsyncApplication`, `AsyncRpcClient`, `EventDispatcher` | asyncio adapter over the **same** connection |
| `export_support_bundle()`, `diagnostics_session_id` | local, explicit, sanitized support ZIP |

## Threading, asyncio and blocking

- One connection: a reader and a writer thread own the socket/pipe; **application callbacks never run on
  them**. Document/window notifications are delivered in order on one event worker; host *requests*
  (`window.before_close`, `app.before_quit`) are answered by a small worker pool so a slow event callback
  does not block close/quit policy.
- A sync callback may call any sync API (including RPCs). A failing handler is reported (stderr + diagnostics)
  and does not stop the other handlers of the same event; unsubscribing a handler from another handler of
  the same event takes effect immediately. `SystemExit`/`KeyboardInterrupt` raised in an *event* callback is
  reported and event delivery continues (call `close()`/`request_quit()` to end the app).
- Host *requests* (`window.before_close`, `app.before_quit`) are **always answered**: a handler exception of
  any kind yields error -32603 with only the exception type (never its text). `SystemExit`/`KeyboardInterrupt`
  in such a handler is answered first, then the SDK sends `app.request_quit` for an orderly shutdown.
- Futures returned by `RpcClient.call_async()` and `Window.open_files/save_file/choose_folder(wait=False)`
  complete on the dedicated `nativehtmlkit-completions` thread, never on the transport reader; their
  done-callbacks may call synchronous RPCs (a done-callback that blocks delays later completions).
- Sync calls block the *calling thread* (default deadline 15 s, `document.load` 30 s, native dialogs none).
  Calling a blocking API on a running asyncio loop emits a `RuntimeWarning` (once) and a diagnostic record.
- `AsyncRpcClient.call()` awaits `asyncio.wrap_future` of the transport future (never `.result()` on the loop).
  `AsyncApplication.on_document_event()` runs plain or `async` callbacks FIFO on the owning loop; the
  returned function disposes the subscription — no invocation starts afterwards, even for events already
  queued. A full dispatcher queue drops the event and increments `dispatcher.dropped`.
- `await AsyncApplication.run()` returns after orderly shutdown; cancelling it closes the connection and
  finishes promptly (the worker polls every 0.1 s; tested < 2 s), leaving no stuck thread.
  `await AsyncApplication.close()` may be called from inside a dispatched handler (with or without `run()`):
  the dispatcher then finishes after the current callback instead of waiting for itself.
- After `app.shutdown`, `create_window()`/`open_html()`/`load_*()` raise `ApplicationShutdownError`.

## Errors

All SDK errors derive from `NativeHTMLKitError` (`classification`, `code`, `operation`, `request_id`, `session_id`,
`outcome_unknown`). **`classification`** is the stable `NHK-…` category on every error. For compatibility `code`
equals `classification` everywhere except `RpcError`, where `code` is the numeric wire code (int) and
`classification` is `NHK-HOST-RPC` (`ClientBusyError`: `NHK-CLIENT-BUSY`); `error_id` is kept as an alias.

| Error | When | Notes |
|---|---|---|
| `RpcError` | the host returned an error | `.code` is the numeric v1 code (-32004 closed/stale id, -32005 busy, -32008 invalid state, …); never parse `.message` |
| `ClientBusyError` (`RpcError`, `local=True`) | SDK refused to queue (128 pending / 8 MiB outgoing) | nothing was sent |
| `RpcTimeoutError` (`TimeoutError`) | local deadline expired (sync and asyncio) | cancellation requested; **`outcome_unknown=True`** — no rollback |
| `DisconnectedError` (`ConnectionError`) | connection ended | every pending call fails with `operation`, `request_id`, `pending_failed`, `__cause__`; `outcome_unknown=True` |
| `ProtocolError` | the **host** sent a malformed frame/JSON, duplicate keys or an invalid response; bad token shape; protocol ≠ 1 | fatal for the session |
| `LocalRequestError` (`ValueError`) | the **caller's** request is not JSON-encodable (NaN, lone surrogate, non-string keys, objects) or exceeds 2 MiB | nothing was sent; the session continues |
| `StaleDocumentError` (`StaleHandleError`, `RuntimeError`) | handle of a replaced/unloaded document or closed window | raised locally before any RPC |
| `ApplicationShutdownError` (`StaleHandleError`, `RuntimeError`) | window/document creation after `app.shutdown` | raised locally |
| `HostVerificationError` (`FileNotFoundError`) | bundled host missing its manifest or not matching its pinned SHA-256 | nothing executed |
| `StartupError` (`RuntimeError`) | direct start cannot launch or connect (incl. arguments/paths containing `{app_dir}`, which the host would substitute) | |

`Application.run()` returns after orderly shutdown **or** after this process called `close()`; it raises
`DisconnectedError` if the host connection was lost. On `app.shutdown` the SDK first delivers the events
already received, then marks **every** window and document handle stale (protocol v1 §7: shutdown implies
all windows closed; the host sends no `closed` event for the last window), then runs `on_shutdown` hooks.

## Diagnostics and support bundles

```bash
NATIVEHTMLKIT_DIAGNOSTICS=trace python app.py         # or: python -m nativehtmlkit --diagnostics trace run pkg.app:main
python -m nativehtmlkit support ./support.zip           # explicit; latest recorded session (or --session ID)
```

- Levels `off|normal|debug|trace` (shared with Core and passed to the host unchanged). Application `print()`
  output and tracebacks are relayed at every level, including `off` (Core ≥ 1.0.3; with a Core 1.0.2 host
  given through `NATIVEHTMLKIT_HOST_BINARY` they are lost at `off`, NHK-CROSS-0007).
- `normal` keeps a bounded in-memory history only;
  `debug`/`trace` also write `python-<session>-<pid>.jsonl` (0600) under `NATIVEHTMLKIT_DIAGNOSTICS_DIR`
  (default `~/.local/state/nativehtmlkit/diagnostics`, Windows `%LOCALAPPDATA%\NativeHTMLKit\diagnostics`).
- `NATIVEHTMLKIT_DIAGNOSTIC_SESSION_ID` (`[A-Za-z0-9._:-]{1,128}`; generated if absent/invalid) is exported to
  the host and backend; Core ≥ 1.0.2 tags its stderr records with it (`diagnostic_session_id`).
- Trace records correlate a host notification (`host.notification`, `event_seq`, event type, element id) →
  `document.dispatch` (handlers / matched) → `callback.started/completed/failed` → `rpc.started`
  (`cause_seq`, `document.command` op name) → `rpc.completed` (duration, error code). This pinpoints e.g.
  "Submit did nothing" (event arrived, `matched: 0`).
- Records never contain RPC params/results, form values, typed text, tokens, URLs or file paths. `method` and
  `op` are allow-listed against the pinned contract (anything else becomes `unknown-method`/`unknown-op`);
  fields named like messages, titles, labels, paths, values etc. are always `[REDACTED]`; other strings must be
  short identifiers. Element ids and event types are recorded at `trace` (author-chosen markup ids). Ring eviction (`history_evicted`), writer-queue loss (`dropped`) and
  I/O errors are counted and exported.
- The support ZIP is created 0600 through an exclusive random temporary file and never replaces an existing
  file unless `--force` / `overwrite=True` is given.
- The support ZIP contains only `manifest.json` and re-sanitized `timeline.jsonl`; never environment
  variables, raw host stderr or screenshots. `NATIVEHTMLKIT_HOST_LOG=PATH` / `run --host-log PATH` opt in
  to a raw host stderr capture (0600): **sensitive** (may contain backend output), never bundled.

## Wire compatibility

Protocol v1 launch variables `UI4ME_ENDPOINT`, `UI4ME_TOKEN`, `UI4ME_APP_ID`, `UI4ME_PROTOCOL_VERSION` are kept
(they are the v1 contract). The SDK validates the token shape, removes all four (and its own
`UI4ME_DIRECT_START`) from `os.environ` right after connecting — also on failure — and never logs them.
`contracts/core-v1-method-matrix.json` is a byte-identical, SHA-pinned copy of Core's `protocol/v1/method-matrix.json`;
a test checks every method/op the SDK sends exists in it.

## Known limitations and host-version notes

- Linux wheels are tagged `manylinux_<glibc floor>_x86_64` from the embedded host (Core 1.0.3: glibc ≥ 2.39,
  e.g. Ubuntu 24.04+/Debian 13); installers refuse older systems. Each wheel records the host's source
  identity (`--version --verbose`), cross-checked against the Core release manifest when packaging and by
  `nativehtmlkit-python version` on the target. `scripts/package-local.py` output is
  reproducible (fixed `SOURCE_DATE_EPOCH`, normalised archives). The sdist contains no host: installing it
  fails with an explanation unless `NATIVEHTMLKIT_DEV_SOURCE_ONLY=1` (then set `NATIVEHTMLKIT_HOST_BINARY`).

- Core ≥ 1.0.2: a backend `request_close` of a non-last window before `app.ready` closes only that window, so an
  `open_html()`/`open_file()` load failure during startup raises a catchable error. Closing the last window (or a
  user close) before `app.ready` still cancels startup. With Core 1.0.1 any early close cancelled startup.
- Closing the last window shuts down without a `window.event` `closed` for it (documented v1 behaviour); rely on
  `app.shutdown` / `on_shutdown`, after which all handles are stale.
- Live bitmaps: only the transport path returned by the host is used (Core 1.0.3: a private runtime directory on
  Linux, `%TEMP%\nativehtmlkit-bitmaps\` on Windows); allocations beyond 64 MiB per document or 256 MiB per host
  are refused with `RpcError` code -32005 (`local=False`).
- Core ≥ 1.0.3 answers `document.load` with `path`/`asset_root` when the file read finishes, so replies to later
  requests can arrive first; the SDK correlates strictly by request id (sync and asyncio).
- Core ≥ 1.0.3 drops `window.event`/`document.event` notifications (counted in `host.diagnostics`
  `dropped_notifications`) if a backend stops reading. The SDK's reader never runs application code, so this
  stays 0; events the SDK itself drops because a callback blocks its own 128-event queue are counted in
  `rpc.dropped_notifications`. Both counters are recorded at shutdown (`host.notifications_dropped`) and
  `Application.host_diagnostics()` returns the host's counters. Do not block event callbacks for long.
- Core ≥ 1.0.3 presents a new window when its first document loads (at the latest after 750 ms); on Windows
  `observed.visible` in `window.state()` is `false` until then. New windows are kept inside the monitor's work area;
  `width`/`height` stay as requested, `physical_size`/`observed.position` report the actual geometry.
- Drag/resize regions (`data-ui4me-drag`, `data-ui4me-resize`) work only on frameless windows (`decorations=False`).
- A callback blocked forever in user code keeps its daemon worker thread; `close()` joins callback workers for at
  most 0.5 s in total, then leaves them and records `callback.worker_abandoned`.
- A blocking SDK call on a running asyncio loop is allowed but warns once (`RuntimeWarning`) and records
  `rpc.sync_call_on_event_loop`.
- Core ≥ 1.0.2 at `trace` emits metadata-only `rpc.received`/`rpc.completed` (same request ids as the SDK's
  `py-N`), `notify.sent` and `request.sent`, so SDK and host timelines correlate exactly; 1.0.1 hosts emit none
  and lack `diagnostic_session_id`.
- After a protocol violation a desktop (non-headless) host stays in its failure state until the user closes its
  window.
- If the connection is lost right after `app.shutdown` (force quit, transport failure), events still queued in the
  SDK are not delivered; an orderly shutdown keeps the connection open long enough to deliver them.
- On Linux the backend's initial environment block (`/proc/<pid>/environ`, readable by the same user and root) still
  shows `UI4ME_TOKEN` after the SDK removed it from `os.environ`; the token is single-use (consumed by `host.hello`).

## Development and verification

```bash
bash scripts/test-local.sh                    # unit + fake-host suite (PYTHON=... to choose the interpreter)
NATIVEHTMLKIT_HOST_BINARY=/path/nativehtmlkit-host bash scripts/test-local.sh   # + real-host integration
python scripts/qualify.py --host HOST --host-sha256 SHA --evidence DIR          # PASS/FAIL/BLOCKED results.json
python scripts/package-local.py --out dist --host linux-x64=HOST=SHA --sdist    # wheel(s) + sdist + SHA256SUMS
tests/native/qualify-linuxdev.sh HOST SHA EVIDENCE    # lab: workstation + KDE Wayland desktop
tests/native/qualify-windev.sh 'F:\...\nativehtmlkit-host.exe' SHA EVIDENCE   # lab: Windows SSH + RDP desktop
```

Builds and tests are local only. The one GitHub Actions workflow, `.github/workflows/pypi_publish.yml`, is publish-only: on manual dispatch it uploads the wheels of an existing GitHub Release to PyPI after verifying their checksums. No publication without explicit owner approval. See [`docs/QUALIFICATION.md`](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/docs/QUALIFICATION.md).

## Licence

The SDK's own code is MIT-licensed ([`LICENSE`](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/LICENSE)). Each platform wheel also contains the
prebuilt NativeHTMLKit Core host (MIT) together with its third-party licences and notices (including OFL-1.1 for
the embedded font, MPL-2.0 components and CC-BY-4.0 stylesheets) in `nativehtmlkit/_bin/core-licenses/`.
