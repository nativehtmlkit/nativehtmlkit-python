# Native file dialogs

`Window.open_files`, `save_file` and `choose_folder` show the platform's own dialog, parented to
the window (on Linux through the desktop portal).

## Non-blocking (recommended inside callbacks)

```python
from nativehtmlkit import RpcError

FILTERS = [{"name": "Text files", "extensions": ["txt", "md", "csv"]}]   # no dots

def open_clicked(_event):
    future = window.open_files(title="Open a text file", filters=FILTERS, wait=False)
    future.add_done_callback(opened)

def opened(future):
    try:
        result = future.result()           # {"cancelled": bool, "paths": [...]}
    except RpcError as error:
        status(f"No file dialog here (code {error.code})")
        return
    if result["cancelled"]:
        status("Cancelled")
        return
    load(Path(result["paths"][0]))

document.on("click", open_clicked, element="open")
```

With `wait=False` the event callback returns at once, so other events keep flowing while the
dialog is open. The done-callback runs on an SDK completion thread and may call any SDK method.
`future.cancel()` asks the host to close the dialog.

## Blocking

```python
result = window.save_file(title="Export", file_name="report.csv", filters=[{"name": "CSV", "extensions": ["csv"]}])
if not result["cancelled"]:
    Path(result["paths"][0]).write_text(csv_text, encoding="utf-8")
```

`wait=True` (the default) has no timeout. Inside an event callback it holds up all later document
and window events until the user answers (close/quit decisions are still handled). That is fine for
scripts, less so for interactive windows.

## Options and results

| Method | Options | `paths` |
|---|---|---|
| `open_files` | `multiple=False`, `title`, `directory`, `filters` | one or more paths |
| `save_file` | `file_name`, `title`, `directory`, `filters` | one path (the file is not created for you) |
| `choose_folder` | `title`, `directory` | one directory |

`paths` is empty and `cancelled` is `True` when the user cancelled.

## When dialogs are unavailable

Headless runs (`NATIVEHTMLKIT_TEST_MODE=1`) and sessions without a dialog service raise `RpcError`
-32001; a second dialog on the same window raises -32005. Check `app.capabilities()["file_dialogs"]`
up front (the top-level flag: does the host offer dialogs in this session?) or handle the error as
above. `capabilities()["features"]["file_dialogs"]["available"]` is `None` ("not observed") on a native
desktop with Core 1.0.3, so do not treat `None` as "no dialogs". Either way, and keep a fallback (a path
input field) where it matters. ([checksum.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/checksum.py) combines both.)

## Reading the chosen file

Paths are plain strings: use `pathlib.Path`. Check the size before reading, decode explicitly and
show content with `set_value`/`set_text` (never as markup). The
[file_viewer.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/examples/file_viewer.py) example does this, lists a chosen folder and saves
with "Save As…".

`<input type="file">` in a form is an alternative: the host shows the picker on click and
`document.files("upload")` or `form_data` return the chosen paths.
