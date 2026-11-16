# Environment variables

## Variables you may set

| Variable | Effect |
|---|---|
| `NATIVEHTMLKIT_TEST_MODE=1` | `Application.start()` and `nativehtmlkit-python run` start the host with `--headless`: the whole protocol runs without native windows (for CI and tests). Native services (dialogs, clipboard, external open, attention) then fail with `RpcError` -32001 and there is no user input. |
| `NATIVEHTMLKIT_DIAGNOSTICS` | `off`, `normal` (default), `debug`, `trace`: SDK and host [diagnostics](diagnostics.md) level. |
| `NATIVEHTMLKIT_DIAGNOSTICS_DIR` | Directory for the SDK's diagnostics files (debug/trace). |
| `NATIVEHTMLKIT_DIAGNOSTIC_SESSION_ID` | Correlation id shared by launcher, host and backend; generated when unset or invalid. |
| `NATIVEHTMLKIT_VERBOSE=1` | The launcher also shows the host's informational records. |
| `NATIVEHTMLKIT_HOST_LOG=FILE` | Append the host's raw JSON log records to `FILE` (0600). **Sensitive**: includes backend output. Same as `run --host-log`. |
| `NATIVEHTMLKIT_HOST_BINARY=PATH` | Use this host executable instead of the bundled one (development override; it is **not** hash-verified). `UI4ME_HOST_BINARY` is an accepted older spelling. |
| `NATIVEHTMLKIT_ALLOW_PATH_HOST=1` | If the wheel has no bundled host, allow an unpinned `nativehtmlkit-host` found in an absolute `PATH` entry (a warning is printed). |

Host resolution order: `NATIVEHTMLKIT_HOST_BINARY`, then the bundled host (verified against
`HOST-MANIFEST.json` on every launch), then (only with `NATIVEHTMLKIT_ALLOW_PATH_HOST=1`) `PATH`.
`nativehtmlkit.host_binary()` returns the path that would be used, applying the same checks.

## Variables the SDK sets

| Variable | Where | Meaning |
|---|---|---|
| `PYTHONUNBUFFERED=1`, `PYTHONIOENCODING=utf-8` | backend | Added by `Application.start()` and the runner unless you set them, so `print()` output reaches your console immediately and as UTF-8. |
| `NATIVEHTMLKIT_DIAGNOSTIC_SESSION_ID` | every process | Exported with the effective session id. |
| `UI4ME_DIRECT_START` | host and backend | Internal marker of `Application.start()`; prevents a backend without a host connection from starting another host. Removed in the backend after connecting. |

## Variables the host sets for the backend

`UI4ME_ENDPOINT` (socket path or pipe name), `UI4ME_TOKEN` (single-use 64-hex launch
credential), `UI4ME_APP_ID` and `UI4ME_PROTOCOL_VERSION` (`1`). These are the permanent names of
protocol v1. The SDK reads them once and removes them from `os.environ` when it connects (also
when connecting fails), so child processes of your application never inherit the credential.
Never set them yourself; having only one of the two connection variables raises `StartupError`.
