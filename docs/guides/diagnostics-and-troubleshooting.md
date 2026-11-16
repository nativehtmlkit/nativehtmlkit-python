# Diagnostics and troubleshooting

## First checks

```bash
nativehtmlkit-python version      # SDK, protocol and host provenance (exit 1 if the host is missing/mismatched)
nativehtmlkit-python doctor       # the host's own environment report
```

## Turn on tracing

```bash
NATIVEHTMLKIT_DIAGNOSTICS=trace python app.py
# or: nativehtmlkit-python --diagnostics trace run app:setup
```

Records go to `~/.local/state/nativehtmlkit/diagnostics/` (Linux) or
`%LOCALAPPDATA%\NativeHTMLKit\diagnostics\` (Windows), or `NATIVEHTMLKIT_DIAGNOSTICS_DIR`. They
contain names, ids, counts and timings, never your data. Export one session as a ZIP for a bug
report with `nativehtmlkit-python support bundle.zip`. Details: [diagnostics reference](../reference/diagnostics.md).

## Symptoms

**"My handler never runs."**
Look for `document.dispatch` records with your `event_type`: `matched: 0` means the event arrived
but no subscription matched. Usual causes:
- `element=` names an element that is not the target or an identified ancestor of it. Print
  `event["element"]` and `event["path"]` from a document-wide handler.
- The event does not bubble (`invalid`, `focus`, `blur`, `toggle`, `close`, `mouseenter`):
  subscribe on the target or without `element`.
- You subscribed on an old document. `load_html`/`load_file` create a new `window.document`.
- You expected an event from a programmatic change: `set_value` and friends fire no events.

**`StaleDocumentError`.**
The window closed or the document was replaced. Use `window.document` (not a saved reference),
check `window.closed`, and catch `NativeHTMLKitError` in background threads.

**`RpcError` -32602 "Unknown element ID".**
The id is not in the current document (typo, element removed by a re-render, or the action runs
against the wrong window).

**`RpcError` -32001.**
Not available in this session: headless mode (`NATIVEHTMLKIT_TEST_MODE=1`), no desktop service
(e.g. no file-dialog portal), or platform policy (Wayland placement/focus). See
`app.capabilities()["features"]`.

**`RpcError` -32005.**
A limit: window count, 1 MiB inline HTML, bitmap budget, one native dialog per window, too many
pending requests.

**The window freezes / events arrive late.**
A callback is busy (slow work, `wait=True` dialog). Look at `callback.completed` `duration_ms` in a
trace. Move work to a [thread](background-work.md) or use `wait=False`. Dropped events show up
as `rpc.notification_dropped` and in `app.rpc.dropped_notifications`.

**My `print()` output is missing.**
Backend output is relayed by the launcher on every diagnostics level. When you started the host
yourself (`nativehtmlkit-python-host run --app`), look at the host's standard error.

**The application exits with status 1 right after start.**
Read the relayed traceback. Typical: an exception in `main()`/`setup()`, a window closed before
`app.ready`, start-up took longer than `startup_timeout_ms`, or `app.close()` was called.

**`StartupError` / `HostVerificationError`.**
No usable host: use a platform wheel (Linux x64 glibc 2.39+, Windows x64), not the source
distribution; reinstall if the bundled host fails its SHA-256 check. `NATIVEHTMLKIT_HOST_BINARY`
overrides the host for development.

**CSS does not apply.**
`document.diagnostics()` lists unsupported CSS and pending resources;
`document.computed_style([...], "id")` shows the effective values and
`document.command("explain", element="id", property="color")` explains one.

## An About / Support window

[diagnostics.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/diagnostics.py) puts the useful facts in one window: platform,
renderer and headless state from `app.capabilities()`, which native services the host offers and
whether it has observed them (see below), the desktop preferences, loss counters from
`app.host_diagnostics()` and the SDK recorder, and a **Save support bundle** button:

```python
from nativehtmlkit import diagnostics, export_support_bundle

caps = app.capabilities()
offered = caps["file_dialogs"]                     # top-level flag: the API is enabled in this session
observed = caps["features"]["file_dialogs"]["available"]   # True/False once observed, None before
host = app.host_diagnostics()                      # dropped_notifications, pending_jobs, ...
failures = sum(r["event"] == "callback.failed" for r in diagnostics.recorder().history())
path = export_support_bundle(folder / "support.zip", overwrite=True)   # manifest.json + timeline.jsonl
```

Treat `None` as "not observed", never as "unavailable": on a native desktop, Core 1.0.3 reports
`available: None` for these services (availability is established by the native request itself)
while the top-level flag is `True`; headless it reports `False` for both. The example's
`feature_state()` turns the pair into one of "available", "enabled (not observed)",
"unavailable" or "not available". The top-level flags are `clipboard_text`, `file_dialogs`,
`external_open`, `drag_drop`, `ime` and `accessibility`; the matching feature entries have the same
names except `drag_drop`, which is `incoming_drop`.

The bundle is written locally and contains no document text, form values or paths.

## Testing without a desktop

`NATIVEHTMLKIT_TEST_MODE=1` runs the real host headless. Everything except native services works,
and you can drive forms with `request_submit` and read state back with `get_text`, `query_nodes`,
`computed_style`, `validity` and so on. This repository's `tests/integration/example_checks.py`
tests every example that way.
