# Python SDK qualification

A host+SDK pair is **QUALIFIED** only when every gate below PASSes for that exact host SHA-256 and SDK
`source_tree_sha256`, on both Linux KDE Plasma Wayland and an interactive Windows desktop. BLOCKED is never PASS;
headless or SSH-only results never count as desktop evidence. Evidence lives outside this repo
(Project `verification/<date>-sdk/python/`, git-ignored): `results.json` with one entry per check
(`id, gate, status, command, platform, source_tree_sha256, host_sha256, duration_s, exit_code, log`).

## Gates and how they are executed

| Gate | What | Command (all local; nothing is published) |
|---|---|---|
| G0 | compile, unit + fake-host suite (framing, correlation, cancellation, disconnect, async adapter, diagnostics redaction/loss accounting, review regressions, lifecycle contract), per interpreter | `PYTHON=... bash scripts/test-local.sh` / `scripts\test-local.ps1` |
| G2 | contract: `contracts/core-v1-method-matrix.json` byte-identical to Core's release `protocol/v1/method-matrix.json` and to the SHA pin; every sent method/op exists | `scripts/qualify.py --stages contract` |
| G3 | real host: hello/version, windows, documents, nodes, forms, bitmaps, resources, low-level RPC, stale handles, limits, deadlines (outcome unknown), multi-window, rapid open/close, asyncio adapter, direct start, host-first runner, scaffold, examples, `version`/`doctor` | `NATIVEHTMLKIT_HOST_BINARY=HOST pytest tests/integration` (headless: host `--headless`; `NHK_IT_DESKTOP=1`: real windows) |
| G4 | faults and privacy on the real host: slow/throwing callbacks then quit, host SIGKILL mid-request, malformed frame, oversize payloads, diagnostics overflow disclosure, "Submit did nothing" at normal/trace with a sentinel secret (SDK records, support ZIP), session ID reaching host records, no orphans | same suite (`G4` ids) + GUI `privacy.*`/`diagnostics.*` checks |
| G6 | real desktop with real OS input: window appears, mouse click, keyboard typing, Enter and button submit, drag (frameless drag region), resize (grip), native file dialog shown + cancelled, AT-SPI / UI Automation button exposure, close veto, last-window shutdown, clean exit, no orphans | `tests/native/gui_driver.py` inside the desktop session |
| G8 | packaging + clean install: pinned-SHA platform wheel(s) + sdist + `SHA256SUMS` + `dist-manifest.json`; fresh venv, `--offline --no-index`, wheel only, no Rust on PATH, import, bundled host SHA = pin, protocol 1, console scripts, real-host scenarios from the installed package | `scripts/package-local.py`, `scripts/smoke-installed.py` |

One command per platform (from the lab workstation):

```bash
tests/native/qualify-linuxdev.sh HOST_PATH HOST_SHA256 EVIDENCE_DIR [CORE_RELEASE_DIR]
tests/native/qualify-windev.sh 'F:\...\nativehtmlkit-host.exe' HOST_SHA256 EVIDENCE_DIR
```

The Linux wrapper runs G0/G2/G3/G4/G8 headless on the workstation (Python 3.10 + 3.14), then G3/G4 with real
windows, the installed-wheel smoke with real windows and G6 on the KDE Wayland lab session. The Windows wrapper runs
G0/G2/G3/G4/G8 over admin SSH (Python 3.10 + 3.14) and then, inside the interactive RDP desktop of the test user,
G3/G4 with real windows, installed-wheel smoke and G6. `NHK_GUI_LOCK` serialises shared desktops.

## Current status

Authoritative evidence for the pinned Core 1.0.2 hosts (Linux `702adafc…741d2a`, Windows `64d4502f…8638f4`, both
from Core source `4f63398c`) is Project `verification/2026-11-15-sdk/python/final2/` (`results.json`, `dist/` with
`SHA256SUMS` and `dist-manifest.json`). It was produced after the independent final adversarial review
(`verification/2026-11-15-sdk/final-review/PYTHON.md`, FR-PY-01..18) and its fixes; `final/` is kept but
superseded by that review. The SDK stays **UNQUALIFIED** until the lead records the host+SDK pair; any FAIL or
BLOCKED entry is listed with its reason in `results.json` and Project `verification/.../python/REVIEW.md`.

Added gates since the review: backend output and the fatal traceback survive every diagnostics level including
`off` (direct start and runner, real host); bundled-host SHA verification on every launch path; argument round-trip
through the host manifest; reproducible packaging (two builds byte-identical) and the `manylinux_2_39_x86_64`
tag refused by pip on an older glibc (Docker, glibc 2.36); the reviewer's 22 mutants re-run.

Desktop-mode BLOCKED by design: `test_malformed_frame_from_sdk_ends_session_causally` (a desktop host keeps its
failure window open for the user; covered headless) and, on Windows, `test_scaffolded_app_starts_and_stops_on_sigterm`
(SIGTERM relay is POSIX; Windows launcher kill + job object is covered by `test_examples`). The GUI driver reports
BLOCKED when a foreign NativeHTMLKit window is on the shared desktop.

Known Core item affecting the SDK: NHK-CROSS-0007 (backend output relayed through the host log filter); the SDK's
disclosed interim behaviour is described in the README ("Diagnostics").

Not executed (never reported as PASS): free-threaded CPython, IME composition, DPI scale ≠ 1, screen-reader
journeys beyond element exposure (Orca/NVDA), a pristine Windows VM (installs used the shared winDEV with
uv-managed CPython), performance baselines, an old-glibc *runtime* (only installer refusal is tested).
