"""Folder checksums: hash every file of a folder on a worker thread, with progress and cancel.

What it teaches
  * keeping slow work OFF the event callback: callbacks run one at a time, so a long job
    there would delay every later event; a worker thread keeps the window responsive
  * updating the document from the worker (the SDK is thread-safe), throttled to a few
    updates per second
  * cancelling cooperatively with ``threading.Event``
  * ``on_before_quit``: ask before quitting while a job is running
  * file names are untrusted text: escaped with ``html.escape``

Run:  uv run checksum.py [FOLDER]      (default: the current directory)
Type or browse to a folder, then press Start.
"""
from __future__ import annotations

import hashlib
import sys
import html
import threading
import time
from pathlib import Path

from nativehtmlkit import Application, NativeHTMLKitError, RpcError, Window

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { margin:0; padding:16px 20px; font:14px sans-serif; background:#f5f6f9; color:#1d2230; }
  h1 { font-size:20px; margin:0 0 10px; }
  form { display:flex; gap:8px; }
  input[type=text] { flex:1; padding:7px; font-family:monospace; }
  button { padding:6px 12px; }
  .progress { height:8px; background:#e0e4ec; border-radius:4px; margin:12px 0 6px; }
  #bar { height:8px; width:0%; background:#3b74e8; border-radius:4px; }
  #warning { display:none; background:#fff0c9; padding:8px 12px; border-radius:6px; }
  #warning.shown { display:block; }
  table { width:100%; border-collapse:collapse; background:#fff; font-size:12px; }
  td { padding:4px 8px; border-bottom:1px solid #e6e8ee; font-family:monospace; }
  td.size { text-align:right; color:#5f6879; }
</style></head>
<body>
  <h1>Folder checksums (SHA-256)</h1>
  <form id="job"><input id="folder" type="text" placeholder="Folder path" required>
    <button id="browse" type="button">Browse…</button>
    <button id="start" type="submit">Start</button><button id="cancel" type="button">Cancel</button></form>
  <div class="progress"><div id="bar"></div></div>
  <p id="status">Idle.</p>
  <p id="warning">A job is still running. Cancel it, or quit again to stop it.</p>
  <table><tbody id="results"></tbody></table>
</body></html>"""


def sha256(path: Path, cancel: threading.Event) -> str | None:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if cancel.is_set():
                return None
            digest.update(chunk)
    return digest.hexdigest()


class ChecksumApp:
    def __init__(self, app: Application, window: Window):
        self.app, self.window, self.document = app, window, window.document
        self.cancel = threading.Event()
        self.worker: threading.Thread | None = None
        self.results: dict[str, str] = {}
        self.quit_warned = False
        doc = self.document
        doc.on("submit", lambda _e: self.start(Path(doc.get_value("folder").strip())), element="job")
        doc.on("click", lambda _e: self.cancel.set(), element="cancel")
        doc.on("click", lambda _e: self.browse(), element="browse")
        app.on_before_quit(self.may_quit)
        app.on_shutdown(self.cancel.set)

    @property
    def busy(self) -> bool:
        return self.worker is not None and self.worker.is_alive()

    def browse(self) -> None:
        def done(future):
            try:
                result = future.result()
            except RpcError as error:
                self.status(f"Folder dialog unavailable (code {error.code}); type a path instead.")
                return
            if not result["cancelled"] and result["paths"]:
                self.document.set_value("folder", result["paths"][0])
        self.window.choose_folder(title="Choose a folder to hash", wait=False).add_done_callback(done)

    def start(self, folder: Path) -> threading.Thread | None:
        if self.busy:
            self.status("A job is already running.")
            return None
        if not folder.is_dir():
            self.status(f"Not a folder: {folder}")
            return None
        self.cancel.clear()
        self.results.clear()
        self.quit_warned = False
        self.document.replace_html("results", "")
        self.worker = threading.Thread(target=self._run, args=(folder,), name="checksum-worker", daemon=True)
        self.worker.start()
        return self.worker

    def _run(self, folder: Path) -> None:
        files = sorted(p for p in folder.rglob("*") if p.is_file())
        pending_rows: list[str] = []
        last_update = 0.0
        try:
            for index, path in enumerate(files, 1):
                try:
                    digest = sha256(path, self.cancel)
                except OSError as error:
                    digest = f"unreadable ({error.strerror})"
                if digest is None:
                    break                                   # cancelled
                name = path.relative_to(folder).as_posix()
                self.results[name] = digest
                pending_rows.append(f"<tr><td>{html.escape(digest)}</td><td>{html.escape(name)}</td>"
                                    f'<td class="size">{path.stat().st_size:,}</td></tr>')
                now = time.monotonic()
                if now - last_update > 0.2 or index == len(files):   # throttle UI updates
                    self._flush(pending_rows, index, len(files))
                    pending_rows, last_update = [], now
            self._flush(pending_rows, len(self.results), len(files))
            word = "Cancelled after" if self.cancel.is_set() else "Done:"
            self.status(f"{word} {len(self.results)} of {len(files)} file(s).")
            self.document.remove_class("warning", "shown")
        except NativeHTMLKitError:
            return                                          # window closed while hashing

    def _flush(self, rows: list[str], done: int, total: int) -> None:
        operations = [{"op": "set_attribute", "element": "bar", "name": "style",
                       "value": f"width:{done * 100 // max(total, 1)}%"},
                      {"op": "set_text", "element": "status", "text": f"Hashing… {done}/{total}"}]
        if rows:
            operations.insert(0, {"op": "insert_html", "element": "results", "position": "beforeend",
                                  "html": "".join(rows)})
        self.document.batch(operations)

    def may_quit(self) -> bool:
        """Answer the host's quit request. Runs on an SDK worker; must return promptly."""
        if self.busy and not self.quit_warned:
            self.quit_warned = True
            self.document.add_class("warning", "shown")
            return False                                    # keep running; a second quit is allowed
        self.cancel.set()
        return True

    def status(self, text: str) -> None:
        self.document.set_text("status", text)


def build(app: Application) -> ChecksumApp:
    return ChecksumApp(app, app.open_html(PAGE, title="Checksums", width=760, height=560))


def main() -> None:
    with Application.start(name="Checksums") as app:
        checksum = build(app)
        checksum.document.set_value("folder", sys.argv[1] if len(sys.argv) > 1 else str(Path.cwd()))
        app.run()


if __name__ == "__main__":
    main()
