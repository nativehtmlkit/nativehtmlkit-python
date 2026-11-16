# Python SDK API reference

Reference for `nativehtmlkit` **0.1.2** (bundles NativeHTMLKit Core 1.0.3, public wire protocol
v1; Python 3.10+). Everything listed here is importable from `nativehtmlkit` unless noted.

```python
from nativehtmlkit import Application

def main() -> None:
    with Application.start(name="Hello") as app:
        window = app.open_html('<button id="go">Go</button><p id="out">Ready</p>')
        window.document.on("click", lambda event: window.document.set_text("out", "Clicked"), element="go")
        app.run()

if __name__ == "__main__":
    main()
```

The object model is `Application → Window → Document → Node`. The Rust host owns windows,
rendering and input; Python owns logic and talks to the host over a local, authenticated
connection.

## Reference pages

| Page | Covers |
|---|---|
| [Application](reference/application.md) | `start`, `from_environment`, windows, `run`/`request_quit`/`close`, window/quit/shutdown hooks, clipboard and desktop services, capabilities |
| [Window](reference/window.md) | Loading documents, `state`/`set`, attention, closing and close policies, native file dialogs |
| [Document](reference/document.md) | Events, text/values/attributes, markup, batches, queries, focus and editing, forms, dialogs and popovers, styles, scrolling, resources, `command` |
| [Event objects](reference/events.md) | Members of event dicts, all event types, delegation |
| [Node](reference/node.md) | References to elements without ids, tree walking and node mutations |
| [LiveBitmap](reference/live-bitmap.md) | RGBA surfaces shown by `<img src="ui4me-bitmap://…">` |
| [asyncio](reference/asyncio.md) | `AsyncApplication`, `AsyncRpcClient`, `EventDispatcher` |
| [RpcClient](reference/rpc.md) | The host connection: `call`, `call_async`, `notify`, raw Core v1 methods |
| [Errors](reference/errors.md) | Exception hierarchy, attributes, wire error codes |
| [Diagnostics](reference/diagnostics.md) | Levels, records, session ids, support bundles |
| [Command-line tools](reference/cli-runner.md) | `nativehtmlkit-python run/doctor/version/support`, `nativehtmlkit-python-host`, `nativehtmlkit-new`, `nativehtmlkit-skill` |
| [Environment variables](reference/environment-variables.md) | Test mode, diagnostics, host override |

## Exports of `nativehtmlkit`

| Name | Kind | Reference |
|---|---|---|
| `Application` | class | [application](reference/application.md) |
| `Window` | class | [window](reference/window.md) |
| `Document` | class | [document](reference/document.md) |
| `Node` | class | [node](reference/node.md) |
| `LiveBitmap` | class | [live bitmap](reference/live-bitmap.md) |
| `AsyncApplication`, `AsyncRpcClient`, `EventDispatcher` | classes | [asyncio](reference/asyncio.md) |
| `RpcClient` | class | [rpc](reference/rpc.md) |
| `NativeHTMLKitError`, `RpcError`, `RpcTimeoutError`, `HostDisconnectedError`, `DisconnectedError`, `HostProtocolError`, `ProtocolError`, `StaleDocumentError`, `StartupError` | exceptions | [errors](reference/errors.md) |
| `diagnostics_session_id` | `str` | [diagnostics](reference/diagnostics.md#session-id) |
| `export_support_bundle` | function | [diagnostics](reference/diagnostics.md#support-bundles) |
| `host_binary()` | function → `Path` | The native host that would be launched (verified); see [environment variables](reference/environment-variables.md) |
| `__version__` | `str` | `"0.1.2"` |

Further classes referenced in these pages live in submodules: `nativehtmlkit.errors`
(`StaleHandleError`, `ApplicationShutdownError`, `LocalRequestError`, `HostVerificationError`,
`UnsupportedFeatureError`), `nativehtmlkit.client` (`ClientBusyError`) and
`nativehtmlkit.diagnostics` (`recorder`, `record`, `SESSION_ID`). Modules and names starting with
`_` are private.

## Method index

**Application**: `start` · `from_environment` · `create_window` · `open_html` · `open_file` ·
`ready` · `run` · `request_quit` · `close` · `on_window_event` · `on_before_quit` · `on_shutdown` ·
`clipboard_text` · `set_clipboard_text` · `open_external` · `reveal_file` · `desktop_preferences` ·
`on_desktop_preferences` · `capabilities` · `host_diagnostics` · `async_adapter`

**Window**: `load_html` · `load_file` · `state` · `set` · `request_attention` · `request_close` ·
`on_before_close` · `open_files` · `save_file` · `choose_folder`

**Document**: `on` · `prevent_default` · `set_text` · `get_text` · `set_value` · `get_value` ·
`set_checked` · `get_checked` · `set_attribute` · `remove_attribute` · `add_class` ·
`remove_class` · `replace_html` · `insert_html` · `remove` · `batch` · `query` · `query_nodes` ·
`node` · `node_batch` · `element_at_point` · `focused_element` · `focus` · `blur` ·
`control_selection` · `set_control_selection` · `replace_control_range` · `edit` · `form_data` ·
`request_submit` · `reset_form` · `validity` · `check_validity` · `set_custom_validity` ·
`options` · `set_selected_values` · `files` · `show_dialog` · `close_dialog` · `show_popover` ·
`hide_popover` · `toggle_popover` · `add_stylesheet` · `replace_stylesheet` ·
`remove_stylesheet` · `stylesheets` · `computed_style` · `environment` · `set_environment` ·
`scroll` · `scroll_to` · `scroll_into_view` · `register_resources` · `unregister_resources` ·
`resource_stats` · `purge_unused_resources` · `create_bitmap` · `diagnostics` · `unload` · `command`

**Node**: `inspect` · `children` · `set_text` · `append_text` · `set_attribute` ·
`remove_attribute` · `add_class` · `remove_class` · `insert_html` · `replace_html` ·
`trim_children` · `move_to` · `remove` · `focus` · `blur`

**LiveBitmap**: `present` · `try_present` · `close`

**RpcClient**: `call` · `call_async` · `notify` · `on_request` · `on_notification` · `wait` ·
`flush` · `wait_for_notifications` · `close`

## Rules that apply everywhere

- **Two processes.** `Application.start()` re-runs your script as the host's backend. Keep side
  effects inside `main()`, after `start()`. See [lifecycle](guides/lifecycle.md).
- **Thread-safe.** Any method may be called from any thread. Callbacks run on SDK threads
  ([threading summary](reference/application.md#threading-summary)).
- **Generation-bound handles.** A replaced, unloaded or closed document, its nodes and its window
  raise `StaleDocumentError` locally.
- **Text vs markup.** `set_text`/`set_value` never parse HTML. `replace_html`/`insert_html` parse
  trusted markup only; escape user data with `html.escape`. See [security](guides/security.md).
- **Headless.** With `NATIVEHTMLKIT_TEST_MODE=1` everything except native services works without
  a desktop; those raise `RpcError` -32001.

## More documentation

- [Tutorial: build a todo app](tutorials/todo-app.md)
- [How-to guides](guides/README.md)
- [Architecture](ARCHITECTURE.md)
- [Examples](../examples/README.md)
