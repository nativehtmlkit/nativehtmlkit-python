"""Text file viewer and editor with native Open, Save As and Choose Folder dialogs.

What it teaches
  * ``Window.open_files`` / ``save_file`` / ``choose_folder`` with filters and a start directory
  * ``wait=False``: the dialog returns a Future, so the event callback returns at once and other
    events keep flowing while the dialog is open; the result arrives in a done-callback
  * the dialog result shape ``{"cancelled": bool, "paths": [...]}``
  * graceful degradation: without a desktop session (headless/CI) dialogs fail with RpcError -32001
  * showing file content safely with ``set_value`` (plain text) and escaping file names

Run:  python examples/file_viewer.py
"""
from __future__ import annotations

import html
from concurrent.futures import Future
from pathlib import Path

from nativehtmlkit import Application, RpcError, Window

MAX_BYTES = 512 * 1024
TEXT_SUFFIXES = ["txt", "md", "py", "json", "csv", "log", "toml"]
TEXT_FILTERS = [{"name": "Text files", "extensions": TEXT_SUFFIXES}]   # extensions without the dot

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { margin:0; font:14px sans-serif; background:#f3f4f7; color:#20242c; display:flex; flex-direction:column; height:100vh; }
  header { display:flex; gap:8px; align-items:center; padding:10px 12px; background:#fff; border-bottom:1px solid #d9dce3; }
  button { padding:6px 12px; border:1px solid #b8bfcc; border-radius:5px; background:#fff; cursor:pointer; }
  #path { margin-left:12px; color:#5b6474; font-family:monospace; }
  .body { flex:1; display:flex; min-height:0; }
  aside { width:220px; overflow:auto; background:#fbfbfd; border-right:1px solid #d9dce3; }
  aside ul { list-style:none; margin:0; padding:6px 0; }
  aside li { padding:4px 12px; cursor:pointer; font-family:monospace; }
  aside li:hover { background:#e8eefc; }
  textarea { flex:1; border:0; padding:12px; font:13px monospace; resize:none; }
  footer { padding:6px 12px; background:#fff; border-top:1px solid #d9dce3; color:#5b6474; }
</style></head>
<body>
  <header>
    <button id="open">Open…</button><button id="save-as">Save As…</button><button id="folder">Folder…</button>
    <span id="path">No file</span>
  </header>
  <div class="body">
    <aside><ul id="files"></ul></aside>
    <textarea id="editor" spellcheck="false" placeholder="Open a text file"></textarea>
  </div>
  <footer id="status">Ready.</footer>
</body></html>"""


class FileViewer:
    def __init__(self, window: Window):
        self.window, self.document = window, window.document
        self.current: Path | None = None
        self.folder_files: list[Path] = []
        doc = self.document
        doc.on("click", lambda _e: self.ask_open(), element="open")
        doc.on("click", lambda _e: self.ask_save_as(), element="save-as")
        doc.on("click", lambda _e: self.ask_folder(), element="folder")
        doc.on("click", self._on_file_click, element="files")

    # ----- native dialogs (non-blocking) -----
    def ask_open(self) -> Future:
        start = self.current.parent if self.current else Path.home()
        future = self.window.open_files(title="Open a text file", directory=start, filters=TEXT_FILTERS,
                                        multiple=False, wait=False)
        future.add_done_callback(lambda f: self._dialog_done(f, self.load))
        return future

    def ask_save_as(self) -> Future:
        name = self.current.name if self.current else "untitled.txt"
        future = self.window.save_file(title="Save as", file_name=name, filters=TEXT_FILTERS, wait=False)
        future.add_done_callback(lambda f: self._dialog_done(f, self.save))
        return future

    def ask_folder(self) -> Future:
        future = self.window.choose_folder(title="Show the text files of a folder", wait=False)
        future.add_done_callback(lambda f: self._dialog_done(f, self.show_folder))
        return future

    def _dialog_done(self, future: Future, action) -> None:
        # Runs on an SDK completion thread; calling the synchronous SDK from here is fine.
        try:
            result = future.result()
        except RpcError as error:
            if error.code == -32001:   # unsupported here, e.g. no desktop session (headless)
                self.status("Native file dialogs are not available in this session.")
            else:
                self.status(f"Dialog failed (code {error.code}).")
            return
        except Exception as error:     # window closed, application shutting down, ...
            print("dialog ended:", type(error).__name__)
            return
        if result["cancelled"] or not result["paths"]:
            self.status("Cancelled.")
            return
        action(Path(result["paths"][0]))

    # ----- file operations (also used directly by the tests) -----
    def load(self, path: Path) -> None:
        try:
            if path.stat().st_size > MAX_BYTES:
                self.status(f"{path.name} is larger than {MAX_BYTES // 1024} KiB.")
                return
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            self.status(f"{path.name} is not UTF-8 text.")
            return
        except OSError as error:
            self.status(f"Cannot read {path.name}: {error.strerror}")
            return
        self.current = path
        self.document.set_value("editor", text)          # plain text: never parsed as HTML
        self.document.set_text("path", str(path))
        self.window.set(title=f"{path.name} — File viewer")
        self.status(f"Opened {path.name} ({len(text)} characters).")

    def save(self, path: Path) -> None:
        try:
            path.write_text(self.document.get_value("editor"), encoding="utf-8")
        except OSError as error:
            self.status(f"Cannot save {path.name}: {error.strerror}")
            return
        self.current = path
        self.document.set_text("path", str(path))
        self.status(f"Saved {path.name}.")

    def show_folder(self, folder: Path) -> None:
        suffixes = {"." + e for e in TEXT_SUFFIXES}
        self.folder_files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in suffixes)[:200]
        items = "".join(f'<li id="file-{i}">{html.escape(p.name)}</li>' for i, p in enumerate(self.folder_files))
        self.document.replace_html("files", items or "<li>(no text files)</li>")
        self.status(f"{len(self.folder_files)} text file(s) in {folder.name or folder}.")

    def _on_file_click(self, event: dict) -> None:
        element = event["element"]
        if element.startswith("file-") and element[5:].isdigit():
            self.load(self.folder_files[int(element[5:])])

    def status(self, text: str) -> None:
        self.document.set_text("status", text)


def build(app: Application) -> FileViewer:
    return FileViewer(app.open_html(PAGE, title="File viewer", width=900, height=600))


def main() -> None:
    with Application.start(name="File viewer") as app:
        build(app)
        app.run()


if __name__ == "__main__":
    main()
