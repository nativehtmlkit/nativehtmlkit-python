# Python SDK — public API overview

Import `Application` from `nativehtmlkit`. The object model is `Application → Window → Document → Node` plus `RpcClient`, `AsyncApplication`, `LiveBitmap` and diagnostic helpers.

| Object | Important public entry points |
|---|---|
| `Application` | `start`, `from_environment`, `open_html`, `open_file`, `create_window`, `run`, `close`, `request_quit`, `on_window_event`, `on_shutdown`, `async_adapter`, `capabilities` |
| `Window` | `load_html`, `load_file`, `set`, `state`, `request_close`, `open_files`, `save_file`, `choose_folder`, `document` |
| `Document` | `on`, `set_text`, `set_value`, `set_checked`, `query`, `query_nodes`, `node`, `form_data`, `show_dialog`, `close_dialog`, `show_popover`, `create_bitmap`, `command` |
| `Node` | generation-bound reference to nodes including elements without ID |
| `LiveBitmap` | `present`, `try_present`, `close` |
| `RpcClient` | `call`, `call_async`, `notify`, request/notification callbacks |

A callback may invoke other SDK calls; do not block native UI-sensitive paths needlessly. `Document.on("click", handler, element="id")` returns an unsubscribe function. Document/Node handles become stale when documents are unloaded or windows close. Prefer the public methods; low-level `document.command(op, **fields)` is for the documented Core v1 command surface.

```python
window = app.open_html('<button id="b">Press</button><p id="out"></p>')
stop_listening = window.document.on('click',
    lambda event: window.document.set_text('out', 'Pressed'), element='b')
# Later, when appropriate: stop_listening()
```

Native dialog example: `paths = window.open_files(multiple=True, title="Choose files")`. For asynchronous call-site use `window.open_files(wait=False)` and handle the returned future. A `LiveBitmap` is created by `document.create_bitmap('id', width, height)`, with a matching `<img src="ui4me-bitmap://id">`; supply tightly packed RGBA bytes to `present`.

For exact function signatures and version-specific protocol behavior consult the installed package's Python introspection and the source files `src/nativehtmlkit/application.py`, `asyncio_api.py`, `live_bitmap.py`. Do not assume experimental methods are stable.
