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

## Current status: 0.1.1 release

Released as tag `v0.1.1` at commit `f0b92903b79fbae4d8c292c6a5c8988b99391139` (source-tree SHA-256
`24a32224a78ba19107bc78716fb350236f32437331893c1b0211f7512ff6b535`), bundling Core 1.0.3 (commit
`d73dec36adbe1b1380f982388d13655750e607df`; Linux host
`1cd4e9de701f3ef8d8b870b678765243f2365d69d7352c0543f171ff249c999f`, Windows host
`15967208d2e20d208d69b97bba6f397056e28c57add126909a8734361ae8f8c8`); wire protocol v1 stable (1.0).
Published on GitHub Releases <https://github.com/nativehtmlkit/nativehtmlkit-python/releases/tag/v0.1.1>
and on PyPI <https://pypi.org/project/nativehtmlkit/0.1.1/> (wheels only, uploaded by the
publish-only workflow from the release assets). Artifacts: manylinux_2_39_x86_64 wheel
`5478384b9a10a130166e3d8877b25b13c7d5004a23165e0aa62aa686e7acffe4`, win_amd64 wheel
`5ac1a1ef67b2f88e3f59630e01f0da8149dd4e4aa6b2fcfc05e8d4e77900cdd5`, sdist
`143aecc65cd56373ac7619d9bf8a4207ed5f91ba677409b873641dff29777db2` (byte-reproducible,
`twine check --strict` clean). Evidence (Project, git-ignored):
`verification/2026-11-16-full-release/python/release/results.json` — 187 PASS, 0 FAIL, 4 BLOCKED
(Linux headless 38/0/0, KDE Wayland 56/0/1, Windows headless 37/0/1, Windows RDP 55/0/2,
packaging 1/0/0), Python 3.10–3.14, offline clean-install smoke on both platforms, 29/29 native GUI
checks per desktop. BLOCKED by design: malformed-frame test in desktop mode; POSIX SIGTERM test on
Windows. After publication, `pip install nativehtmlkit==0.1.1` from PyPI was checked on Linux
(import, bundled host hash, a headless application); the PyPI install was not re-checked on Windows.
The 0.1.0 record below applies to 0.1.0 only.

## Previous: 0.1.0 prerelease

Published as a GitHub prerelease: tag `v0.1.0` at commit `7559b5b1f1e678017895789fabe3a1a6f59d5a74`
(source-tree SHA-256 `81d2171524de9fb9ba68377115cf2dca0255dd261a052e5b6c596357367ad1c7`), built from that clean commit
against the clean Core 1.0.2 release directories (Core commit `8a09875cff58aa16b60573ffca24de4d611d60b3`). Not on PyPI;
wire protocol v1 was then still `1.0-rc` (declared stable, 1.0, with Core 1.0.3).

| Artifact | SHA-256 |
|---|---|
| `nativehtmlkit-0.1.0-py3-none-manylinux_2_39_x86_64.whl` (host `702adafc…741d2a`) | `3073066c9ad5fba8a296ba3541110e43511a2c7a4eec5669a76d2113ab59642d` |
| `nativehtmlkit-0.1.0-py3-none-win_amd64.whl` (host `64d4502f…8638f4`) | `183ba566d70e931c72ee28c73ae60890ede2e40d070ac26824c978bac2d867fc` |
| `nativehtmlkit-0.1.0.tar.gz` (no host) | `5779033930aa9af1ba5812c5da19751e71b6f3cc0e2b05aca6039aedcee31bf1` |

Two builds from the commit were byte-identical. Evidence (Project, git-ignored):
`verification/2026-11-15-sdk/python/release/results.json` — **187 PASS, 0 FAIL, 4 BLOCKED**, every entry on the
tree hash above and the pinned hosts: Linux headless 38/0/0, Linux KDE Wayland desktop 56/0/1, Windows headless
37/0/1, Windows interactive RDP desktop 55/0/2, reproducible dist build 1/0/0. Python 3.10–3.14 unit suites and
offline clean-install smoke on both platforms; 29/29 native GUI checks per desktop with real input.

BLOCKED by design: `test_malformed_frame_from_sdk_ends_session_causally` in desktop mode on both desktops (a desktop
host keeps its failure window open for the user; it passes headless) and `test_scaffolded_app_starts_and_stops_on_sigterm`
on Windows (SIGTERM relay is POSIX; launcher kill + job object is covered by `test_examples`).

Deviation (Windows interactive): in the one-command run the interactive scheduled task ended with 0xC000013A
(STATUS_CONTROL_C_EXIT) during the GUI stage. The task's own visible PowerShell console window lay above the native
file dialog; the driver's activating click and the following Alt+F4 ("native close") hit that console and closed it.
Desktop integration (26 PASS, 2 BLOCKED) and installed-wheel smoke had passed before that. The desktop stages were
re-run with the same commit, host and wheel, changing only `start_interactive.ps1 -Hidden` (no console window):
55 PASS, 0 FAIL, 2 BLOCKED. Both runs' evidence is kept (`win-results/windows-desktop/INTERRUPTED.md`,
`win-results/windows-desktop-rerun/`). The harness now passes `-Hidden` by default (commit after `v0.1.0`; the
released wheels were built from `7559b5b`, before this harness change).

Earlier evidence (`final/`, `final2/`, attempts and rehearsals) is superseded by `release/` and kept for traceability.
The independent final adversarial review (`verification/2026-11-15-sdk/final-review/PYTHON.md`, FR-PY-01..18) and its
fixes are recorded in `verification/2026-11-15-sdk/python/REVIEW.md`.

Known Core item affecting the SDK: NHK-CROSS-0007 (backend output relayed through the host log filter); the SDK's
disclosed interim behaviour is described in the README ("Diagnostics").

Not executed (never reported as PASS): free-threaded CPython, IME composition, DPI scale ≠ 1, screen-reader
journeys beyond element exposure (Orca/NVDA), a pristine Windows VM (installs used the shared winDEV with
uv-managed CPython), performance baselines, an old-glibc *runtime* (only installer refusal is tested).
