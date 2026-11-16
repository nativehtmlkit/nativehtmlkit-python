# Packaging your app

A NativeHTMLKit application is an ordinary Python program that depends on the `nativehtmlkit`
wheel; the wheel bundles the native host for its platform.

## Project layout

`nativehtmlkit-new myapp --name "My App"` creates a starting point:

```text
myapp/
  app.py          Application.start() entry point
  index.html      the page, loaded with app.open_file(HERE / "index.html")
  style.css       referenced from index.html (relative to the HTML file)
  pyproject.toml  depends on nativehtmlkit
  app.toml        optional manifest pinning the interpreter
```

Locate assets relative to your code, never the current directory:

```python
HERE = Path(__file__).resolve().parent
window = app.open_file(HERE / "index.html")
```

For an installed package, keep HTML/CSS/images as package data and resolve them with
`importlib.resources.files("mypackage") / "ui" / "index.html"` (a real file path when installed
normally), or load the markup as a string with `load_html(..., asset_root=...)`.

## Distribute as a Python package

```toml
[project]
name = "myapp"
version = "1.0.0"
requires-python = ">=3.10"
dependencies = ["nativehtmlkit==0.1.2"]

[project.gui-scripts]
myapp = "myapp.app:main"
```

Users install with `pip install myapp` or `uv tool install myapp`, and start `myapp` (or
`python -m myapp` with a `myapp/__main__.py` that calls `main()`). `Application.start()` re-runs the
same command as the backend. Both forms were checked on Linux; on Windows, `python -m myapp` uses
the same mechanism as `python app.py`, while generated `.exe` script launchers were not part of the
0.1.2 checks, so try yours before relying on it.

Platform support follows the `nativehtmlkit` wheels: Linux x64 (glibc 2.39+) and Windows x64,
Python 3.10+. The source distribution of `nativehtmlkit` has no host.

## Identity and data

- Give the application a stable `app_id` (`Application.start(app_id="com.example.MyApp")`). It
  controls single-instance hand-off and names the per-app directories from `desktop.paths`.
- Store user data under `app.rpc.call("desktop.paths")["data"]` (or `config`/`state`), create
  the directory yourself and write files atomically (write a temporary file, then `os.replace`).
- Set `name`, `version` and `icon` in `Application.start(...)`.

## Explicit manifests

For launchers, desktop entries or installers that should start a fixed interpreter, use a manifest
and `nativehtmlkit-python-host run --app /path/to/app.toml` ([format](../reference/cli-runner.md#nativehtmlkit-python-host)).
`{app_dir}` in manifest strings is replaced by the manifest's directory. The backend then connects
with `Application.start()` or `Application.from_environment()`.

## Before you ship

- Run your UI headless in CI (`NATIVEHTMLKIT_TEST_MODE=1`) and assert on DOM state.
- Test once on each real desktop you support: native dialogs, clipboard, focus and window
  placement depend on the platform.
- Do not set `NATIVEHTMLKIT_HOST_BINARY` in production; the bundled host is hash-verified on every
  launch.
