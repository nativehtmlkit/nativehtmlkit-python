# Examples and demos

The runnable examples, with what each one teaches, are indexed in
[examples/README.md](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/README.md)
and listed machine-readably in
[examples/catalog.toml](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/catalog.toml).
The catalogue ids are the parity keys shared with the PowerShell SDK's examples catalogue
(`async-counter` is Python-only).

- **Start here:** `hello.py`, `counter.py`, then the [todo tutorial](tutorials/todo-app.md), which builds `todo.py`.
- **Forms, tables and the DOM:** `signup_form.py`, `data_table.py`, `process_viewer.py`, `dom_explorer.py`.
- **Windows, dialogs and files:** `window_manager.py`, `settings_dialog.py`, `file_viewer.py`, `bulk_rename/` ([tutorial](tutorials/bulk-rename.md)).
- **Keyboard, desktop services and diagnostics:** `keyboard_shortcuts.py`, `text_toolbox.py`, `diagnostics.py`.
- **Background work and live updates:** `log_viewer.py`, `checksum.py`, `async_jobs.py`, `live_chart.py`, `process_dashboard/` ([tutorial](tutorials/process-dashboard.md)), `focus_timer.py`.
- **Python-specific (asyncio):** `async_counter.py`.

Two ways to start an example:

```bash
python examples/focus_timer.py                              # Application.start()
cd examples && python -m nativehtmlkit run focus_timer:setup   # host-first runner, setup(app)
```

The public showcase repository has a guided gallery covering several features in one window:
[examples/python-sdk/gallery.py](https://github.com/nativehtmlkit/nativehtmlkit/blob/main/examples/python-sdk/gallery.py).

The Python UI library is separate: it offers reactive controls built on the public SDK, whereas the
SDK gives direct control of documents, windows and events. See the
[UI library](https://github.com/nativehtmlkit/nativehtmlkit_ui).
