# NativeHTMLKit for Python

**Native desktop windows from ordinary Python and local HTML/CSS.** The Rust Core host draws the interface; Python handles application logic and events. No browser, JavaScript, HTTP server, or Node.js runtime is required.

[PyPI package](https://pypi.org/project/nativehtmlkit/) · [Public developer guide](https://github.com/nativehtmlkit/nativehtmlkit) · [API reference](docs/API.md) · [Examples](examples/hello.py)

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

Run `python hello.py` or `uv run hello.py`. `Application.start()` launches a supervised host and re-executes the backend: keep side effects inside `main()`. Alternatively `python -m nativehtmlkit run module:main` runs a `main(app)` backend entrypoint once.

## What you can build

- Multiple windows, native file/folder dialogs and application lifecycle policies.
- HTML/CSS documents, event callbacks, DOM updates, forms and selection.
- Clipboard, desktop preferences, diagnostics, bounded live-bitmap surfaces.
- Asyncio callbacks and completion futures over the same local host connection.

For layouts, reactive state and reusable controls, use the separate [Python UI library](https://github.com/nativehtmlkit/nativehtmlkit_ui) rather than inventing new SDK surface.

## Learn more

| Guide | Purpose |
|---|---|
| [API reference](docs/API.md) | Real public Python objects, methods and error handling |
| [Architecture](docs/ARCHITECTURE.md) | Lifecycle, host, IPC and threading |
| [Examples](docs/EXAMPLES.md) | Next steps and the interactive demo gallery |
| [Build and testing](docs/BUILD.md) | Release source, wheels and qualification |
| [Public tutorials](https://github.com/nativehtmlkit/nativehtmlkit) | Screenshots, learning path and capability matrix |
| [Skill](skills/nativehtmlkit-python/SKILL.md) | Agent instructions to build a Python app |

**Released package:** 0.1.1. This README update does not mean a newer wheel has been published; a marketplace description update requires its own verified patch release.

## Project navigation

- [Overview and tutorials](https://github.com/nativehtmlkit/nativehtmlkit) — public developer landing page.
- [Capability and platform matrix](https://github.com/nativehtmlkit/nativehtmlkit/blob/main/docs/capabilities/matrix.md) — which API works where.
- [Known limitations](https://github.com/nativehtmlkit/nativehtmlkit/blob/main/docs/capabilities/limitations.md) — known defects and qualification limits.
- Active private development work is tracked in `nativehtmlkit-project`, not in this repository's documentation.
