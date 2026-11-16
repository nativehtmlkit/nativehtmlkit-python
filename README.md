# NativeHTMLKit for Python

**Native desktop windows from ordinary Python and local HTML/CSS.** The Rust Core host draws the interface; Python handles application logic and events. No browser, JavaScript, HTTP server, or Node.js runtime is required.

[PyPI package](https://pypi.org/project/nativehtmlkit/) · [Tutorial](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/docs/tutorials/todo-app.md) · [How-to guides](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/docs/guides/README.md) · [API reference](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/docs/API.md) · [Examples](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/README.md) · [Public developer guide](https://github.com/nativehtmlkit/nativehtmlkit)

![Illustrative NativeHTMLKit application gallery, not an actual captured desktop screenshot](https://raw.githubusercontent.com/nativehtmlkit/nativehtmlkit/main/assets/demo-placeholder.png)

*Illustration only — not a verified screenshot. Run the [real gallery demo](https://github.com/nativehtmlkit/nativehtmlkit/tree/main/examples/python-sdk) to inspect the actual application. The illustration will be replaced after interactive desktop verification.*

## Install

```bash
python -m pip install nativehtmlkit
# or: uv add nativehtmlkit
nativehtmlkit-python version
```

Published wheels target Windows x64 and Linux x64 (the currently released Linux wheel specifies **glibc 2.39+**). Check platform compatibility before assuming a pip install will work. The source distribution does **not** bundle the native host; use a compatible published wheel for normal use. Python 3.10+.

## Your first app

Save as `hello.py`:

```python
from nativehtmlkit import Application

def main():
    with Application.start(name="Hello NativeHTMLKit") as app:
        window = app.open_html('''<main style="padding:24px;font-family:sans-serif">
<h1>Hello from Python</h1><button id="hello">Click me</button><p id="status">Ready</p>
</main>''')
        window.document.on("click", lambda event:
            window.document.set_text("status", "Clicked!"), element="hello")
        app.run()

if __name__ == "__main__":
    main()
```

Run `python hello.py` or `uv run hello.py`. `Application.start()` launches a supervised host and re-executes the backend: keep side effects inside `main()`. Alternatively `python -m nativehtmlkit run module:setup` imports your module once and calls `setup(app)` ([lifecycle](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/docs/guides/lifecycle.md)).

`set_text` and `set_value` treat input as plain text; `replace_html` and `insert_html` parse trusted markup, so escape user data with `html.escape` ([security](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/docs/guides/security.md)). For automated tests, `NATIVEHTMLKIT_TEST_MODE=1` runs the real host headless.

## What you can build

| Example | Shows |
|---|---|
| [todo.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/todo.py) | Forms, delegated events, keyboard, escaping, JSON persistence |
| [signup_form.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/signup_form.py) | Native constraint validation, custom rules, `form_data` |
| [window_manager.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/window_manager.py) | Several windows, window state, close vetoes |
| [file_viewer.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/file_viewer.py) | Native Open / Save As / Choose Folder dialogs |
| [settings_dialog.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/settings_dialog.py) | HTML `<dialog>`, popovers, dark mode |
| [log_viewer.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/log_viewer.py) · [checksum.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/checksum.py) | Background threads, batched updates, cancel |
| [live_chart.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/live_chart.py) | Live RGBA bitmap rendered from Python |
| [async_jobs.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/async_jobs.py) | asyncio tasks, async callbacks |
| [text_toolbox.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/text_toolbox.py) | Clipboard, links, desktop preferences |
| [data_table.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/data_table.py) · [dom_explorer.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/dom_explorer.py) | Rendering data, nodes without ids |

All [15 examples](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/README.md) are started and checked against the real host by the test suite.

For layouts, reactive state and reusable controls, use the separate [Python UI library](https://github.com/nativehtmlkit/nativehtmlkit_ui) rather than inventing new SDK surface.

## Learn more

| Guide | Purpose |
|---|---|
| [Tutorial: build a todo app](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/docs/tutorials/todo-app.md) | Learn the SDK step by step |
| [How-to guides](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/docs/guides/README.md) | Events, DOM updates, forms, windows, dialogs, threads, asyncio, bitmaps, packaging, security, troubleshooting |
| [API reference](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/docs/API.md) | Every public class, method, parameter, result and error |
| [Architecture](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/docs/ARCHITECTURE.md) | Processes, host verification, IPC, threads, document generations |
| [Examples](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/README.md) | 15 runnable applications and what each teaches |
| [Build and testing](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/docs/BUILD.md) | Release source, wheels and qualification |
| [Public tutorials](https://github.com/nativehtmlkit/nativehtmlkit) | Screenshots, learning path and capability matrix |
| [Skill](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/skills/nativehtmlkit-python/SKILL.md) | Agent instructions to build a Python app |

**Package version:** 0.1.2 (bundles NativeHTMLKit Core 1.0.3, public wire protocol v1). 0.1.2 refreshes documentation and the bundled agent skill; the SDK API is unchanged from 0.1.1.

## Project navigation

- [Overview and tutorials](https://github.com/nativehtmlkit/nativehtmlkit) — public developer landing page.
- [Capability and platform matrix](https://github.com/nativehtmlkit/nativehtmlkit/blob/main/docs/capabilities/matrix.md) — which API works where.
- [Known limitations](https://github.com/nativehtmlkit/nativehtmlkit/blob/main/docs/capabilities/limitations.md) — known defects and qualification limits.
- Active private development work is tracked in `nativehtmlkit-project`, not in this repository's documentation.
