---
name: nativehtmlkit-python
description: Build native HTML/CSS desktop applications using the public NativeHTMLKit Python SDK on Linux KDE Wayland or Windows.
---

# NativeHTMLKit Python SDK

Use `nativehtmlkit` package (Python 3.10+). Always check SDK version, host compatibility and target desktop. This skill is for **SDK** objects (`Application`, `Window`, `Document`), not the reactive UI library.

## First window

```python
from nativehtmlkit import Application
with Application.start(name='Hello') as app:
    w = app.open_html('<button id="go">Click</button><p id="out">Ready</p>')
    w.document.on('click', lambda e: w.document.set_text('out', 'Clicked'), element='go')
    app.run()
```

`Application.start()` starts a supervised host and may rerun the script in the backend; avoid side effects before it. An alternative `python -m nativehtmlkit run module:main` accepts `main(app)` and launches the backend once.

Use public document helpers, `on` unsubscribe, `Window.open_files/save_file/choose_folder`, `Document.show_dialog`, `Document.create_bitmap` with RGBA8. Treat stale generation handles as errors; do not assume native dialogs exist in headless sessions.

## Architecture guardrails

Never import SDK private modules, access Core Rust internals, call a CLI as the transport, add a browser/JS server, or change Core from an SDK task. For components and reactive state, use the separate `nativehtmlkit-ui-python` skill. See [examples](references/examples.md) and [full documentation](https://github.com/nativehtmlkit/nativehtmlkit-python).
