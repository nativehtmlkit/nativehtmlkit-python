# Examples and demos

The runnable examples, with what each one teaches, are indexed in
[examples/README.md](../examples/README.md):

- **Start here:** `hello.py`, then the [tutorial](tutorials/todo-app.md), which builds `todo.py`.
- **Forms and DOM:** `signup_form.py`, `data_table.py`, `dom_explorer.py`.
- **Windows and dialogs:** `window_manager.py`, `settings_dialog.py`, `file_viewer.py`.
- **Background work:** `log_viewer.py`, `checksum.py`, `live_chart.py`, `async_counter.py`, `async_jobs.py`.
- **Desktop services and lifecycle:** `text_toolbox.py`, `focus_timer.py`.

Two ways to start an example:

```bash
python examples/focus_timer.py                              # Application.start()
cd examples && python -m nativehtmlkit run focus_timer:setup   # host-first runner, setup(app)
```

The public showcase repository has a guided gallery covering several features in one window:
[examples/python-sdk/gallery.py](https://github.com/nativehtmlkit/nativehtmlkit/blob/main/examples/python-sdk/gallery.py).

The Python UI library is separate: it offers reactive controls built on the public SDK, whereas the
SDK gives direct control of documents, windows and events. See the
[public getting started guide](https://github.com/nativehtmlkit/nativehtmlkit/blob/main/docs/getting-started/python.md).
