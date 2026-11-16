"""Live log viewer: a background thread streams records into a bounded, filterable view.

What it teaches
  * calling the SDK from your own thread (every Document method is thread-safe)
  * one ``batch`` per flush: append many rows and trim the oldest in a single transaction
  * ``trim_children`` keeps memory bounded; ``set_scroll_follow`` keeps the newest row in view
  * filtering by toggling a CSS class instead of re-rendering
  * stopping a worker cleanly on shutdown (``on_shutdown``) and escaping every log message

Run:  python examples/log_viewer.py
The records come from a simulated service; replace ``simulated_records`` with a real source.
"""
from __future__ import annotations

import html
import itertools
import random
import threading
import time
from datetime import datetime

from nativehtmlkit import Application, NativeHTMLKitError, Window

MAX_ROWS = 500

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { margin:0; background:#0f141c; color:#d7dde8; font:13px sans-serif; display:flex; flex-direction:column; height:100vh; }
  header { display:flex; gap:12px; align-items:center; padding:10px 14px; background:#18202c; border-bottom:1px solid #2a3443; }
  header h1 { font-size:15px; margin:0 12px 0 0; }
  select, button { background:#243044; color:#d7dde8; border:1px solid #3a4a62; border-radius:5px; padding:5px 9px; }
  #count { margin-left:auto; color:#8a96a8; }
  #log { flex:1; overflow:auto; font-family:monospace; padding:6px 0; }
  .line { padding:1px 14px; white-space:pre-wrap; }
  .line .time { color:#6c7a8e; } .line .lvl { display:inline-block; width:52px; font-weight:bold; }
  .DEBUG .lvl { color:#7d8ba1; } .INFO .lvl { color:#6cb6ff; } .WARN .lvl { color:#f2c14e; } .ERROR .lvl { color:#ff6b6b; }
  .ERROR { background:#2a1518; }
  /* Filtering is pure CSS: the controller only switches a class on #log. */
  #log.min-INFO .DEBUG, #log.min-WARN .DEBUG, #log.min-WARN .INFO,
  #log.min-ERROR .DEBUG, #log.min-ERROR .INFO, #log.min-ERROR .WARN { display:none; }
</style></head>
<body>
  <header>
    <h1>Service log</h1>
    <label>Level <select id="level">
      <option value="DEBUG">Debug</option><option value="INFO" selected>Info</option>
      <option value="WARN">Warning</option><option value="ERROR">Error</option></select></label>
    <label><input id="pause" type="checkbox"> Pause</label>
    <button id="clear">Clear</button>
    <span id="count">0 records</span>
  </header>
  <div id="log" class="min-INFO"></div>
</body></html>"""


def simulated_records():
    """An endless stream of (level, message) pairs; messages may contain markup characters."""
    users = ["alice", "bob", "<script>", "chloé"]
    for n in itertools.count(1):
        level = random.choices(["DEBUG", "INFO", "WARN", "ERROR"], [5, 10, 2, 1])[0]
        yield level, f"request #{n} by {random.choice(users)} took {random.randint(3, 900)} ms"


class LogViewer:
    def __init__(self, window: Window):
        self.document = doc = window.document
        self.total = 0
        self.paused = threading.Event()
        self.stopped = threading.Event()
        self._lock = threading.Lock()     # flushes come from the worker AND from callbacks
        doc.command("set_scroll_follow", element="log", follow=True)
        doc.on("change", self._on_level, element="level")
        doc.on("change", lambda e: (self.paused.set() if e.get("checked") else self.paused.clear()), element="pause")
        doc.on("click", lambda _e: self.clear(), element="clear")

    def append(self, records: list[tuple[str, str]]) -> None:
        """Add rows and drop the oldest beyond MAX_ROWS, as ONE document transaction."""
        if not records:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        rows = "".join(
            f'<div class="line {level}"><span class="time">{stamp}</span> '
            f'<span class="lvl">{level}</span>{html.escape(message)}</div>'
            for level, message in records)
        with self._lock:
            self.document.batch([
                {"op": "insert_html", "element": "log", "position": "beforeend", "html": rows},
                {"op": "trim_children", "element": "log", "keep": MAX_ROWS, "from": "start"},
            ])
            self.total += len(records)
            self.document.set_text("count", f"{self.total} records")

    def clear(self) -> None:
        with self._lock:
            self.document.replace_html("log", "")
            self.total = 0
            self.document.set_text("count", "0 records")

    def set_level(self, level: str) -> None:
        for name in ("DEBUG", "INFO", "WARN", "ERROR"):
            self.document.remove_class("log", f"min-{name}")
        self.document.add_class("log", f"min-{level}")

    def _on_level(self, event: dict) -> None:
        self.set_level(event.get("value") or "INFO")

    def run_producer(self, source, *, interval: float = 0.25) -> threading.Thread:
        """Collect records for ``interval`` seconds, then flush them in one batch."""
        def worker() -> None:
            pending: list[tuple[str, str]] = []
            deadline = time.monotonic() + interval
            for record in source:
                if self.stopped.is_set():
                    return
                if not self.paused.is_set():
                    pending.append(record)
                time.sleep(0.02)
                if time.monotonic() >= deadline:
                    try:
                        self.append(pending)
                    except NativeHTMLKitError:
                        return  # window closed or application shutting down: stop quietly
                    pending, deadline = [], time.monotonic() + interval
        thread = threading.Thread(target=worker, name="log-producer", daemon=True)
        thread.start()
        return thread


def build(app: Application) -> LogViewer:
    viewer = LogViewer(app.open_html(PAGE, title="Log viewer", width=820, height=560))
    app.on_shutdown(viewer.stopped.set)
    return viewer


def main() -> None:
    with Application.start(name="Log viewer") as app:
        viewer = build(app)
        viewer.run_producer(simulated_records())
        app.run()


if __name__ == "__main__":
    main()
