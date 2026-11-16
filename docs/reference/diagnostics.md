# Diagnostics

The SDK records **privacy-safe** structured diagnostics: event names, ids, counters, durations and
error codes, never RPC parameters or results, document text, form values, file paths, titles or
credentials. Recording never raises into your code and never blocks the transport.

```python
from nativehtmlkit import diagnostics_session_id, export_support_bundle
```

## Levels

Set with `NATIVEHTMLKIT_DIAGNOSTICS` (or `nativehtmlkit-python --diagnostics LEVEL ...`):

| Level | Recorded | Written to disk |
|---|---|---|
| `off` | nothing | no |
| `normal` (default) | `ERROR` and `WARN` records, kept in memory (last 256) | no |
| `debug` | also `INFO`/`DEBUG` | yes, JSON Lines |
| `trace` | also `TRACE` (every RPC, notification, callback and dispatch) | yes |

The same variable controls the host's own records, which it writes to its standard error. The
launcher relays the backend's output at every level and summarises host warnings and errors;
informational host records are shown with `NATIVEHTMLKIT_VERBOSE=1` (set automatically by
`--diagnostics trace`).

## Files

At `debug`/`trace` each process writes `python-<session>-<pid>.jsonl` (mode 0600, at most 16 MiB)
into the diagnostics directory:

| Platform | Directory |
|---|---|
| any | `NATIVEHTMLKIT_DIAGNOSTICS_DIR` if set |
| Windows | `%LOCALAPPDATA%\NativeHTMLKit\diagnostics` |
| Linux | `~/.local/state/nativehtmlkit/diagnostics` |

Each line is one record:

```json
{"schema_version": 1, "timestamp": "2026-11-16T09:12:03.120511+00:00", "session_id": "py-3f…",
 "component": "python-sdk", "pid": 41872, "level": "TRACE", "event": "rpc.completed",
 "context": {"request_id": "py-12", "method": "document.command", "duration_ms": 1, "failed": false, "error_code": null}}
```

Context values that are not short identifiers are replaced by `"[REDACTED]"`; method and op names
outside the published Core contract become `"unknown-method"`/`"unknown-op"`.

Useful record names:

| Event | Meaning |
|---|---|
| `host.authenticated` | Connected with protocol v1 |
| `rpc.started`, `rpc.completed`, `rpc.timeout`, `rpc.cancel_requested` | Requests (`method`, `op`, `duration_ms`, `error_code`, `cause_seq`: the event whose callback made the call) |
| `host.notification` | A notification arrived (`method`, `event_type`, `element`, `event_seq`) |
| `document.dispatch` | An event reached a document: `handlers` registered, `matched` for this event. `matched: 0` explains "my handler never ran". |
| `callback.started`, `callback.completed`, `callback.failed` | Your callbacks (`exception_type` on failure) |
| `rpc.notification_dropped`, `host.notifications_dropped`, `callback.queue_overflow` | Events lost because callbacks were too slow |
| `transport.disconnected`, `transport.closed` | Connection ended by the host / by `close()` |
| `document.error`, `application.shutdown_received` | Document failures and orderly shutdown |

## Session id

`diagnostics_session_id` (also `nativehtmlkit.diagnostics.SESSION_ID`) identifies this run. It is
taken from `NATIVEHTMLKIT_DIAGNOSTIC_SESSION_ID` if that holds 1–128 characters of
`A-Z a-z 0-9 . _ : -`, else generated (`py-<hex>`), and exported again in the environment, so
the launcher, the host and the backend share one id. Every `NativeHTMLKitError` carries it as
`session_id`.

## Support bundles

```python
export_support_bundle(path, *, capture_environment=False, session=None, directory=None, overwrite=False) -> Path
```

Write a local ZIP with `manifest.json` (counts, losses, SDK version, optionally OS/architecture/
Python version) and `timeline.jsonl` (the re-sanitised records of one session; default: this
process's session, from its files or, without files, its in-memory history). Raises
`FileExistsError` unless `overwrite=True`, `ValueError` for an invalid session id. Never included:
RPC payloads, form values, credentials, environment variables, raw host output, screenshots.

From the command line (uses the most recently recorded session unless `--session` is given):

```bash
NATIVEHTMLKIT_DIAGNOSTICS=trace python app.py          # reproduce the problem
nativehtmlkit-python support bundle.zip                # then export it
```

## Host counters

`app.host_diagnostics()` returns the host's view (`phase`, `windows`, `pending_jobs`,
`dropped_notifications`, `logging` counters); `app.host_dropped_notifications` holds the final
count after `run()`. `document.diagnostics()` lists render/layout diagnostics of a document
(unsupported CSS, pending resources).

## In-process access

`nativehtmlkit.diagnostics.recorder()` returns the process recorder: `summary()` (level, record
count, drops, file name) and `history()` (the in-memory records). `nativehtmlkit.diagnostics.record(event, level=..., **fields)`
adds a record with the same sanitisation.

See [diagnostics and troubleshooting](../guides/diagnostics-and-troubleshooting.md).
