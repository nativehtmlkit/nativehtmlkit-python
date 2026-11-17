---
name: nativehtmlkit-python
description: Build native HTML/CSS desktop applications using the public NativeHTMLKit Python SDK on Linux KDE Wayland or Windows.
---

# NativeHTMLKit Python SDK

Use the `nativehtmlkit` package (0.1.2, Python 3.10+; wheels for Linux x64 glibc 2.39+ and Windows x64). Check the SDK version, host compatibility and target desktop first (`nativehtmlkit-python version`). This skill is for **SDK** objects (`Application`, `Window`, `Document`, `Node`), not the reactive UI library.

## First window

```python
from nativehtmlkit import Application

def main():
    with Application.start(name='Hello') as app:
        w = app.open_html('<button id="go">Click</button><p id="out">Ready</p>')
        w.document.on('click', lambda e: w.document.set_text('out', 'Clicked'), element='go')
        app.run()

if __name__ == '__main__':
    main()
```

`Application.start()` starts a supervised host and reruns the script as its backend; keep side effects inside `main()`, after `start()`. Alternative: `uv run -m nativehtmlkit run module:setup` imports the module once and calls `setup(app)`, then `app.run()`.

## Rules

- `set_text`/`set_value` are plain text. `replace_html`/`insert_html` parse trusted markup: `html.escape()` every untrusted value, including attribute values. Never build ids, CSS or tag names from user data.
- Subscribe once on a container (`document.on('click', cb, element='list')`) and parse `event['element']` (nearest id) / `event['path']`. Non-bubbling events (`invalid`, `focus`, `blur`, `toggle`, `close`) need the target itself or no `element`.
- Callbacks run after native dispatch on one ordered thread; use `document.prevent_default(...)` up front to cancel defaults. Keep callbacks short; move slow work to threads (the SDK is thread-safe) or asyncio (`app.async_adapter()`).
- Programmatic `set_value`/`set_checked` fire no events. `request_submit` runs validation and fires `submit`/`invalid`, which makes forms testable headless.
- Native file dialogs: `window.open_files/save_file/choose_folder(wait=False)` returns a Future with `{'cancelled', 'paths'}`. Clipboard, dialogs, `open_external` and attention raise `RpcError` -32001 headless or when unavailable: handle it.
- Links never navigate: handle `link_activated` and call `app.open_external(url)` after checking the scheme.
- Handles are generation-bound: after reload/unload/close, old `Document`/`Node`/`Window` objects raise `StaleDocumentError`. Use `window.document`; catch `NativeHTMLKitError` in threads.
- Quit with `app.request_quit()`; policies via `app.on_before_quit`, `window.on_before_close`; cleanup in `app.on_shutdown` (no SDK calls there). `app.close()` is an abrupt disconnect (host exit status 1).
- Live pixels: `document.create_bitmap('id', w, h)` + `<img src="ui4me-bitmap://id">`, straight-alpha RGBA8 frames, `try_present` from producer threads.
- Test with `NATIVEHTMLKIT_TEST_MODE=1` (real host, headless, no synthetic input); read state back with `get_text`, `query_nodes`, `validity`, `computed_style`.

## Architecture guardrails

Never import SDK private modules (`_bootstrap`, ...), access Core Rust internals, call a CLI as the transport, add a browser/JS server, or change Core from an SDK task. For components and reactive state, use the separate `nativehtmlkit-ui-python` skill. See [examples](references/examples.md), the [API reference](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/docs/API.md) and the [how-to guides](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/docs/guides/README.md).
