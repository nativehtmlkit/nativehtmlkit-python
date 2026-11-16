# Python SDK examples

Runnable applications for `nativehtmlkit` 0.1.2. Each file starts with a docstring that says what
it teaches and how to run it; all of them use only the public SDK API and run on Linux and Windows.
[`catalog.toml`](catalog.toml) lists them in machine-readable form; each `id` is shared with the
[PowerShell SDK examples](https://github.com/nativehtmlkit/nativehtmlkit-powershell/tree/main/examples),
which use the same ids for their counterparts.

```bash
python -m pip install nativehtmlkit
python examples/todo.py
```

## Start here

| Example | What it is | What it teaches |
|---|---|---|
| [hello.py](hello.py) | **Hello**: The smallest complete app: a greeting form that writes untrusted text safely. | application lifecycle, get_value, set_text |
| [counter.py](counter.py) | **Counter**: A counter with a step selector, limits and a bounded change history. | shared state, event delegation, batch updates, trim_children |
| [todo.py](todo.py) | **Todo list**: Add, edit, complete, filter and delete tasks, saved to a JSON file. | form submit, delegated list events, escaping user text, keyboard editing, atomic JSON persistence |

## Forms, tables and the DOM

| Example | What it is | What it teaches |
|---|---|---|
| [signup_form.py](signup_form.py) | **Sign-up form**: Account sign-up form with HTML validation, a custom rule and a result summary. | constraint validation, invalid events, set_custom_validity, form_data, reset_form |
| [data_table.py](data_table.py) | **Inventory data table**: Searchable, sortable, paged table rendered from data, with a details pane. | input/change events, batch updates, rendering rows safely |
| [process_viewer.py](process_viewer.py) | **Process viewer**: Sortable, filterable table of running processes. | rendering data as a table, input event value, sortable headers with aria-sort |
| [dom_explorer.py](dom_explorer.py) | **DOM explorer**: Tree view of a live DOM with selecting, editing, moving and deleting nodes. | Node, query_nodes, children, inspect, move_to, stale nodes |

## Windows, dialogs and files

| Example | What it is | What it teaches |
|---|---|---|
| [window_manager.py](window_manager.py) | **Multiple windows**: Note windows managed from a main window, with a close veto for unsaved notes. | several windows, window state, on_window_event, on_before_close |
| [settings_dialog.py](settings_dialog.py) | **Settings dialog**: Settings in a modal HTML dialog, saved to JSON, with a dark-mode switch. | show_dialog/close_dialog, close event, popovers, set_environment |
| [file_viewer.py](file_viewer.py) | **File viewer**: Text viewer and editor with Open, Save As and a folder listing. | open_files/save_file/choose_folder, wait=False futures, file filters, -32001 fallback |
| [bulk_rename/app.py](bulk_rename/app.py) | **Bulk rename**: Rename many files with find/replace, a live preview, a confirmation dialog and undo. | open_file with index.html and style.css, pure planning logic, live preview, folder dialog fallback, undo |

## Keyboard, desktop services and diagnostics

| Example | What it is | What it teaches |
|---|---|---|
| [keyboard_shortcuts.py](keyboard_shortcuts.py) | **Snippet editor**: A snippet editor with keyboard shortcuts, Tab indentation and a help popover. | keydown chords, prevent_default, replace_control_range, control selection |
| [text_toolbox.py](text_toolbox.py) | **Clipboard tool**: Text transforms with copy and paste, links and desktop preferences. | clipboard, link_activated, open_external, capabilities |
| [diagnostics.py](diagnostics.py) | **About and support**: An About/Support window: capabilities, preferences, counters and a support bundle. | capabilities, desktop_preferences, host_diagnostics, export_support_bundle |

## Background work and live updates

| Example | What it is | What it teaches |
|---|---|---|
| [log_viewer.py](log_viewer.py) | **Log viewer**: Live, filterable log stream fed by a background thread. | batch, trim_children, CSS-class filtering, worker threads |
| [checksum.py](checksum.py) | **Checksums**: SHA-256 of every file in a folder, computed in a worker thread with cancel. | worker thread, throttled progress, cooperative cancel, on_before_quit |
| [async_jobs.py](async_jobs.py) | **Background jobs**: Concurrent jobs with progress bars and cancel buttons. | asyncio tasks, async callbacks, AsyncRpcClient, cancellation |
| [live_chart.py](live_chart.py) | **Live chart**: A 30 fps scrolling line chart drawn into a live bitmap. | create_bitmap, RGBA frames, try_present from a producer thread |
| [process_dashboard/dashboard.py](process_dashboard/dashboard.py) | **Process dashboard**: Live process monitor that refreshes in the background, with filter, sort, pause and copy. | background thread, thread-safe updates, pause/resume, clipboard |
| [focus_timer.py](focus_timer.py) | **Focus timer**: A countdown timer that asks before quitting while it runs. | both entry styles, on_before_quit, on_shutdown, request_attention |

## Python-specific

| Example | What it is | What it teaches |
|---|---|---|
| [async_counter.py](async_counter.py) | **Async counter**: A counter whose callback is an async function (asyncio basics). | async_adapter, awaitable document.command |

## Tutorials

- [Build a todo app](../docs/tutorials/todo-app.md) builds `todo.py` in steps; the intermediate
  programs are in [tutorial/](tutorial/):
  [step1_window.py](tutorial/step1_window.py) ·
  [step2_add.py](tutorial/step2_add.py) ·
  [step3_complete_delete.py](tutorial/step3_complete_delete.py) ·
  [step4_edit_keyboard.py](tutorial/step4_edit_keyboard.py).
- [Bulk rename](../docs/tutorials/bulk-rename.md) builds [bulk_rename/](bulk_rename/)
  (`app.py`, `index.html`, `style.css`).
- [Process dashboard](../docs/tutorials/process-dashboard.md) builds
  [process_dashboard/](process_dashboard/) in three programs:
  [step1_snapshot.py](process_dashboard/step1_snapshot.py) ·
  [step2_filter.py](process_dashboard/step2_filter.py) ·
  [dashboard.py](process_dashboard/dashboard.py), with the helper
  [processes.py](process_dashboard/processes.py).

## Two ways to start an example

```bash
python examples/focus_timer.py                                  # Application.start()
cd examples && python -m nativehtmlkit run focus_timer:setup    # host-first runner, setup(app)
```

## Without a desktop

Native dialogs, clipboard, opening links and window attention need a desktop session. In
headless mode (`NATIVEHTMLKIT_TEST_MODE=1`) and on systems without those services they fail with
`RpcError` -32001, and the examples show a message instead of crashing.

## How the examples are tested

- `tests/integration/test_examples.py` starts every entry of `catalog.toml` and every tutorial
  step against the real host until the application is ready, stops it and checks that no process
  is left. It fails when a program under `examples/` is missing from the catalogue.
- `tests/integration/test_example_behaviour.py` runs one check per catalogue entry
  (`tests/integration/example_checks.py`): it calls the example's `build(...)` function inside a
  host-supervised backend, drives it through the example's own methods and the public SDK
  (`request_submit`, `set_value`, ...) and reads the DOM back through the public API. It fails when
  an entry has no check.

```bash
NATIVEHTMLKIT_HOST_BINARY=/path/to/nativehtmlkit-host python -m pytest tests/integration
```

Headless mode has no synthetic pointer or keyboard input; clicks, typing and native dialogs are
exercised on a real desktop.

## More

- [Getting started](../docs/getting-started.md), [how-to guides](../docs/guides/README.md) and
  [API reference](../docs/API.md)
- The [public gallery demo](https://github.com/nativehtmlkit/nativehtmlkit/tree/main/examples/python-sdk)
- For reusable components and reactive state, the [Python UI library](https://github.com/nativehtmlkit/nativehtmlkit_ui)

## Screenshots

Real captures on KDE Plasma 6.6 Wayland (100% scaling) with Core 1.0.3, Python SDK 0.1.2, taken by
running each example unchanged. Windows looks the same apart from the window frame.

| | |
|---|---|
| [async_counter](async_counter.py)<br>![async_counter](../docs/images/examples/py-sdk-async_counter.png) | [async_jobs](async_jobs.py)<br>![async_jobs](../docs/images/examples/py-sdk-async_jobs.png) |
| [checksum](checksum.py)<br>![checksum](../docs/images/examples/py-sdk-checksum.png) | [data_table](data_table.py)<br>![data_table](../docs/images/examples/py-sdk-data_table.png) |
| [dom_explorer](dom_explorer.py)<br>![dom_explorer](../docs/images/examples/py-sdk-dom_explorer.png) | [file_viewer](file_viewer.py)<br>![file_viewer](../docs/images/examples/py-sdk-file_viewer.png) |
| [focus_timer](focus_timer.py)<br>![focus_timer](../docs/images/examples/py-sdk-focus_timer.png) | [live_chart](live_chart.py)<br>![live_chart](../docs/images/examples/py-sdk-live_chart.png) |
| [log_viewer](log_viewer.py)<br>![log_viewer](../docs/images/examples/py-sdk-log_viewer.png) | [settings_dialog](settings_dialog.py)<br>![settings_dialog](../docs/images/examples/py-sdk-settings_dialog.png) |
| [signup_form](signup_form.py)<br>![signup_form](../docs/images/examples/py-sdk-signup_form.png) | [text_toolbox](text_toolbox.py)<br>![text_toolbox](../docs/images/examples/py-sdk-text_toolbox.png) |
| [todo](todo.py)<br>![todo](../docs/images/examples/py-sdk-todo.png) | [window_manager](window_manager.py)<br>![window_manager](../docs/images/examples/py-sdk-window_manager.png) |
