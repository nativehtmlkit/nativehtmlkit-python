# Command-line tools

Installing `nativehtmlkit` adds four commands. In a uv project, start them with `uv run` (for
example `uv run nativehtmlkit-python version`). `uv run -m nativehtmlkit` is the same as
`nativehtmlkit-python`. `nativehtmlkit-new` also works before you have a project:
`uvx --from nativehtmlkit nativehtmlkit-new DIRECTORY`.

| Command | Purpose |
|---|---|
| [`nativehtmlkit-python`](#nativehtmlkit-python) | Run an entry point in a managed backend, check the installation, export support bundles |
| [`nativehtmlkit-python-host`](#nativehtmlkit-python-host) | The bundled native host's own command line (run a manifest, doctor) |
| [`nativehtmlkit-new`](#nativehtmlkit-new) | Create a new application project |
| [`nativehtmlkit-skill`](#nativehtmlkit-skill) | Install the bundled coding-agent skill |

## `nativehtmlkit-python`

```text
nativehtmlkit-python [--diagnostics {off,normal,debug,trace}] {run,doctor,version,support} ...
```

`--diagnostics LEVEL` sets `NATIVEHTMLKIT_DIAGNOSTICS` for this process, the host and the backend
(`trace` also sets `NATIVEHTMLKIT_VERBOSE=1`). Errors print `nativehtmlkit: <Type>: <message>`
and exit with status 1.

### `run`

```text
nativehtmlkit-python run MODULE:CALLABLE [--name NAME] [--host-log FILE]
```

The host-first runner. It starts the native host, which starts a backend process that imports
`MODULE` (from the current directory / `PYTHONPATH`), calls `CALLABLE(app)` with a connected
`Application` and then `app.run()`. Your module is imported **only** in the backend, once, after
the launch credential was removed from the environment, so module-level code does not run twice.

- `CALLABLE` may be a dotted attribute path (`pkg.app:App.main`) that does not start with `_`. It receives the `Application` and should create at least one window and register
  callbacks; it should not call `app.run()` itself (if it does, the runner's call returns at once).
- If `CALLABLE` returns a coroutine, the runner runs it with `asyncio.run(...)` before `app.run()`.
- `--name` (default `"NativeHTMLKit App"`) is the application name. The application id is derived
  from the entry point and name; every launch is independent (`instance = "multiple"`), the
  window limit is 16, start-up and shutdown timeouts are 30 s and 5 s.
- `--host-log FILE` appends the host's raw JSON log records to `FILE` (mode 0600). **Sensitive**:
  the records include backend output and therefore application data.
- `NATIVEHTMLKIT_TEST_MODE=1` runs the host headless.

The exit status is the host's: 0 after an orderly quit, 1 when the application failed (for
example an unhandled exception in `CALLABLE`, or a lost backend connection), 128+N after signal N.

```bash
cd examples
uv run -m nativehtmlkit run focus_timer:setup --name "Focus timer"
uv run -m nativehtmlkit run async_jobs:amain
```

### `doctor`

`uv run nativehtmlkit-python doctor` runs the host's own environment report (JSON: host version, build
identity, OS, desktop session variables, per-app paths, renderer, containment). It does not open
windows. Times out after 15 s.

### `version`

`uv run nativehtmlkit-python version` prints JSON: `sdk_version`, `client_version`, `protocol_version`,
`python` and `host` (`source`: `bundled`/`environment`/`path`, `path`, `sha256`, the bundled
`manifest`, `manifest_match`, the host's `source_identity` and `source_identity_match`). It starts
no application. Exit status 1 when no host is found or the bundled host does not match its pinned
manifest.

### `support`

```text
nativehtmlkit-python support OUTPUT.zip [--session ID] [--force]
```

Export a redacted [support bundle](diagnostics.md#support-bundles) of the most recently recorded
diagnostics session (or `--session`). `--force` replaces an existing file.

## `nativehtmlkit-python-host`

Forwards its arguments to the bundled (SHA-256-verified) native host. On Linux the Python wrapper
replaces itself with the host process, so signals reach the host directly.

```text
nativehtmlkit-python-host run --app app.toml     # start an application from a manifest
nativehtmlkit-python-host doctor
nativehtmlkit-python-host --version
```

A manifest names the backend program to start. A minimal one, as written by `nativehtmlkit-new`:

```toml
[app]
id = "org.example.notes"
name = "Notes"
version = "1.0.0"

[backend]
program = "/path/to/python"          # the interpreter; pin your virtual environment's python
args = ["{app_dir}/app.py"]          # {app_dir} is the manifest's directory
cwd = "{app_dir}"

[host]
startup_timeout_ms = 30000
shutdown_timeout_ms = 5000
max_windows = 4
instance = "single"
```

`[backend.env]` may add environment variables (not the `UI4ME_*`/`NATIVEHTMLKIT_*` transport
names or `*_HOST_*` keys, which the host rejects). The backend connects with
`Application.start()` (which only connects when started by a host) or
`Application.from_environment()`.

## `nativehtmlkit-new`

```text
nativehtmlkit-new DIRECTORY [--name NAME] [--python INTERPRETER]
```

Create a project in a new or empty directory: `app.py` (an `Application.start()` app with a
form handler), `index.html`, `style.css`, `pyproject.toml` (depends on `nativehtmlkit>=0.1.1`) and
an optional `app.toml` manifest that pins `--python` (default: the current interpreter; under `uvx`
that is a temporary interpreter in uv's cache, so point `program` at your project's `.venv`
interpreter before using the manifest). The app id
is `org.nativehtmlkit.examples.<slug>`; change it for your own application. Refuses to overwrite a
non-empty directory (exit status 2). Then:

```bash
cd DIRECTORY
uv run app.py
```

## `nativehtmlkit-skill`

```text
nativehtmlkit-skill {install,status,uninstall} [--agents all|claude,codex,opencode,copilot,cursor,gemini]
                    [--scope user|project] [--project PATH] [--force] [--dry-run]
```

Install the `nativehtmlkit-python` agent skill bundled in the wheel into the skill folders of
coding agents, per user (default) or per project (`--scope project --project PATH`). Only this
skill is managed: a modified or foreign directory is replaced or removed only with `--force`.
No network access. Exit status 1 if any target failed.

| Agent | User folder | Project folder |
|---|---|---|
| claude | `~/.claude/skills` | `.claude/skills` |
| codex | `~/.agents/skills` | `.agents/skills` |
| opencode | `~/.config/opencode/skills` | `.opencode/skills` |
| copilot | `~/.copilot/skills` | `.github/skills` |
| cursor | `~/.cursor/skills` | `.cursor/skills` |
| gemini | `~/.gemini/skills` | `.gemini/skills` |
