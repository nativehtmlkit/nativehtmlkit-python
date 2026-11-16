# Tutorial: a live process dashboard

You will build **Process Dashboard**: a native window with a table of running processes that
refreshes itself in the background, can be filtered and sorted, paused, and copied to the
clipboard. It works the same on Linux and Windows.

**Time:** about 30 minutes. **You need:** Python 3.10+ on Linux x64 (glibc 2.39+) or Windows x64,
`python -m pip install nativehtmlkit`, and the first window from
[getting started](../getting-started.md).

The code is in
[examples/process_dashboard](https://github.com/nativehtmlkit/nativehtmlkit-python/tree/main/examples/process_dashboard):
one program per step plus a small helper module. The repository's test suite runs all of them
against the real native host.

## Step 0: a process snapshot helper

The dashboard needs a list of processes as plain data. `processes.py` reads it with the standard
library only: `/proc` on Linux and the Win32 API through `ctypes` on Windows. It has no user
interface, and you can treat it as a black box (in your own projects `psutil` does the same job).
Save it next to your program:

```python title="processes.py"
"""Process snapshot helper for the process dashboard tutorial (docs/tutorials/process-dashboard.md).

``list_processes()`` returns plain data (name, pid, memory in MB, CPU time in seconds) using only
the standard library: ``/proc`` on Linux and the Win32 API (through ``ctypes``) on Windows. In your
own code, ``psutil`` is a good alternative. This module has no user interface and is imported by
step1_snapshot.py, step2_filter.py and dashboard.py.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Process:
    name: str
    pid: int
    memory_mb: float
    cpu_seconds: float


def list_processes() -> list[Process]:
    """A snapshot of running processes: name, id, resident memory (MB) and CPU time (s)."""
    return _windows_processes() if sys.platform == "win32" else _linux_processes()


def _linux_processes() -> list[Process]:
    tick, page = os.sysconf("SC_CLK_TCK"), os.sysconf("SC_PAGE_SIZE")
    result = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat", encoding="utf-8", errors="replace") as handle:
                stat = handle.read()
        except OSError:          # the process ended, or access is denied
            continue
        # The name is in parentheses and may itself contain spaces or ')'.
        name = stat[stat.index("(") + 1:stat.rindex(")")]
        fields = stat[stat.rindex(")") + 2:].split()
        cpu = (int(fields[11]) + int(fields[12])) / tick       # utime + stime
        memory = int(fields[21]) * page / 2**20                 # rss pages
        result.append(Process(name, int(entry), round(memory, 1), round(cpu, 1)))
    return result


def _windows_processes() -> list[Process]:
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD), ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", wintypes.LONG), ("dwFlags", wintypes.DWORD),
                    ("szExeFile", wintypes.WCHAR * 260)]

    class MemoryCounters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (name, ctypes.c_size_t) for name in ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                                                 "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                                                 "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.OpenProcess.restype = wintypes.HANDLE
    snapshot = kernel32.CreateToolhelp32Snapshot(0x2, 0)        # TH32CS_SNAPPROCESS
    if snapshot in (None, wintypes.HANDLE(-1).value):
        return []
    result = []
    try:
        entry = ProcessEntry(dwSize=ctypes.sizeof(ProcessEntry))
        more = kernel32.Process32FirstW(wintypes.HANDLE(snapshot), ctypes.byref(entry))
        while more:
            memory = cpu = 0.0
            handle = kernel32.OpenProcess(0x1000, False, entry.th32ProcessID)   # QUERY_LIMITED_INFORMATION
            if handle:                                                      # None: access denied
                counters = MemoryCounters(cb=ctypes.sizeof(MemoryCounters))
                if kernel32.K32GetProcessMemoryInfo(wintypes.HANDLE(handle), ctypes.byref(counters), counters.cb):
                    memory = counters.WorkingSetSize / 2**20
                times = [wintypes.FILETIME() for _ in range(4)]            # creation, exit, kernel, user
                if kernel32.GetProcessTimes(wintypes.HANDLE(handle), *map(ctypes.byref, times)):
                    cpu = sum((t.dwHighDateTime << 32 | t.dwLowDateTime) for t in times[2:]) / 1e7
                kernel32.CloseHandle(wintypes.HANDLE(handle))
            name = entry.szExeFile.removesuffix(".exe")
            result.append(Process(name, entry.th32ProcessID, round(memory, 1), round(cpu, 1)))
            more = kernel32.Process32NextW(wintypes.HANDLE(snapshot), ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(wintypes.HANDLE(snapshot))
    return result
```

`list_processes()` returns `Process(name, pid, memory_mb, cpu_seconds)` records. Processes that
end while they are read, or that you may not inspect, are skipped or reported with zero memory
and CPU time.

## Step 1: a table of the busiest processes

```python title="step1_snapshot.py"
"""Process dashboard tutorial, step 1: show a table of the busiest processes in a native window.

What it teaches
  * ``Application.start`` -> ``open_html`` -> ``replace_html`` -> ``app.run()``
  * building HTML rows from data with ``html.escape``
  * filling the page before ``app.run()`` announces readiness, so the window opens complete

Run:    python examples/process_dashboard/step1_snapshot.py
Guide:  docs/tutorials/process-dashboard.md (step 1 of 3)
"""
from __future__ import annotations

import html

from nativehtmlkit import Application
from processes import list_processes

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { font: 14px sans-serif; margin: 0; background: #11161f; color: #e6ebf3; }
  main { padding: 18px 22px; }
  h1 { font-size: 20px; margin: 0 0 12px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #2a3445; }
  th { color: #9fb0c8; font-weight: 600; }
  td.num, th.num { text-align: right; }
</style></head>
<body><main>
  <h1>Top processes by memory</h1>
  <table>
    <thead><tr><th>Name</th><th class="num">Id</th><th class="num">Memory (MB)</th><th class="num">CPU (s)</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
</main></body></html>"""


def rows_html(processes) -> str:
    # Process names are not under your control: escape them before they become markup.
    return "".join(f'<tr><td>{html.escape(p.name)}</td><td class="num">{p.pid}</td>'
                   f'<td class="num">{p.memory_mb:,.1f}</td><td class="num">{p.cpu_seconds:,.1f}</td></tr>'
                   for p in processes)


def build(app: Application):
    window = app.open_html(PAGE, title="Process Dashboard", width=720, height=560)
    top = sorted(list_processes(), key=lambda p: p.memory_mb, reverse=True)[:15]
    window.document.replace_html("rows", rows_html(top))
    return window.document


def main() -> None:
    # The host runs this script again as its backend: keep side effects inside main().
    with Application.start(name="Process Dashboard") as app:
        build(app)
        app.run()


if __name__ == "__main__":
    main()
```

Run `python step1_snapshot.py`.

- The page is a Python string. Every element the code changes has an `id`: here only the table
  body `rows`.
- `rows_html` builds `<tr>` rows with f-strings. Process names are not under your control, so each
  one goes through `html.escape` before it becomes markup.
- `replace_html("rows", ...)` replaces the children of `<tbody id="rows">`.
- `build()` fills the table before `app.run()` announces that the app is ready, so the window
  opens with a full table. `build()` is also what the tests call.
- `from processes import list_processes` works because the script's folder is on `sys.path`, in
  the backend run as well.

## Step 2: filter and sort

```python title="step2_filter.py"
"""Process dashboard tutorial, step 2: filter and sort the table.

What it teaches
  * ``input``, ``change`` and ``submit`` events that all call one ``update_view`` function
  * reading controls with ``get_value``
  * ``set_text`` for text that must never be parsed as HTML

Run:    python examples/process_dashboard/step2_filter.py
Guide:  docs/tutorials/process-dashboard.md (step 2 of 3)
"""
from __future__ import annotations

import html

from nativehtmlkit import Application, Document
from processes import list_processes

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { font: 14px sans-serif; margin: 0; background: #11161f; color: #e6ebf3; }
  main { padding: 18px 22px; }
  h1 { font-size: 20px; margin: 0 0 12px; }
  form { display: flex; gap: 8px; margin-bottom: 10px; }
  input, select { background: #1b2331; color: #e6ebf3; border: 1px solid #3a475c; border-radius: 5px; padding: 6px; }
  #filter { flex: 1; }
  button { background: #3574c6; color: white; border: 0; border-radius: 5px; padding: 6px 12px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #2a3445; }
  th { color: #9fb0c8; font-weight: 600; }
  td.num, th.num { text-align: right; }
  #summary { color: #9fb0c8; }
</style></head>
<body><main>
  <h1>Processes</h1>
  <form id="view-form">
    <input id="filter" type="search" placeholder="Filter by name" aria-label="Filter by name">
    <select id="sort" aria-label="Sort by">
      <option value="memory">Memory</option><option value="cpu">CPU time</option><option value="name">Name</option>
    </select>
    <button id="apply">Refresh</button>
  </form>
  <p id="summary"></p>
  <table>
    <thead><tr><th>Name</th><th class="num">Id</th><th class="num">Memory (MB)</th><th class="num">CPU (s)</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
</main></body></html>"""

SORT_KEYS = {
    "memory": (lambda p: p.memory_mb, True),
    "cpu": (lambda p: p.cpu_seconds, True),
    "name": (lambda p: p.name.lower(), False),
}
SHOWN = 25


def update_view(document: Document) -> None:
    needle = document.get_value("filter").strip().lower()
    key, descending = SORT_KEYS.get(document.get_value("sort"), SORT_KEYS["memory"])
    everything = list_processes()
    shown = [p for p in everything if needle in p.name.lower()]
    top = sorted(shown, key=key, reverse=descending)[:SHOWN]
    document.replace_html("rows", "".join(
        f'<tr><td>{html.escape(p.name)}</td><td class="num">{p.pid}</td>'
        f'<td class="num">{p.memory_mb:,.1f}</td><td class="num">{p.cpu_seconds:,.1f}</td></tr>' for p in top))
    document.set_text("summary", f"Showing {len(top)} of {len(everything)} processes")


def build(app: Application) -> Document:
    window = app.open_html(PAGE, title="Process Dashboard", width=720, height=600)
    document = window.document
    # Callbacks run later, on the SDK's event thread, and may call any SDK method.
    document.on("input", lambda _event: update_view(document), element="filter")
    document.on("change", lambda _event: update_view(document), element="sort")
    document.on("submit", lambda _event: update_view(document), element="view-form")
    update_view(document)
    return document


def main() -> None:
    with Application.start(name="Process Dashboard") as app:
        build(app)
        app.run()


if __name__ == "__main__":
    main()
```

- Three subscriptions call the same `update_view` function: `input` on the search field (every
  keystroke), `change` on the sort `<select>`, and `submit` on the form (Enter or the **Refresh**
  button, which submits the form because it is a `<button>` inside it).
- `get_value` reads the current filter text and the selected sort option.
- `set_text` writes the summary: text is never parsed as HTML.
- `SORT_KEYS` maps each `<option value>` to a sort key and direction, so an unexpected value falls
  back to memory order instead of failing.

## Step 3: background refresh, pause and copy

`list_processes()` takes a moment on a busy machine, and calling it in a callback holds up every
later event. The final version collects processes in a **background thread** that refreshes every
few seconds, and the callbacks only filter and sort the cached snapshot.

```python title="dashboard.py"
"""Process dashboard: a live process monitor (final code of the process dashboard tutorial).

What it teaches
  * collecting data in a background thread and updating the page from it (SDK calls are
    thread-safe), so slow work never blocks the window's event callbacks
  * a refresh loop that waits on a ``threading.Event`` (wakes early to resume or to quit)
  * pausing with a checkbox (the ``change`` event carries ``checked``)
  * filtering and sorting a cached snapshot under a lock
  * copying the table to the clipboard with ``set_clipboard_text`` (and a fallback without one)
  * stopping the thread from ``app.on_shutdown``

Run:    python examples/process_dashboard/dashboard.py [--refresh-seconds 3]
Guide:  docs/tutorials/process-dashboard.md (step 3 of 3)
"""
from __future__ import annotations

import argparse
import html
import threading
import time

from nativehtmlkit import Application, Document, NativeHTMLKitError, RpcError
from processes import list_processes

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { font: 14px sans-serif; margin: 0; background: #11161f; color: #e6ebf3; }
  main { padding: 18px 22px; }
  header { display: flex; align-items: baseline; gap: 12px; }
  h1 { font-size: 20px; margin: 0 0 12px; }
  #status { color: #9fb0c8; }
  form { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
  input, select { background: #1b2331; color: #e6ebf3; border: 1px solid #3a475c; border-radius: 5px; padding: 6px; }
  #filter { flex: 1; }
  button { background: #3574c6; color: white; border: 0; border-radius: 5px; padding: 6px 12px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #2a3445; }
  th { color: #9fb0c8; font-weight: 600; }
  td.num, th.num { text-align: right; }
  #summary { color: #9fb0c8; }
</style></head>
<body><main>
  <header><h1>Processes</h1><span id="status" role="status">Collecting...</span></header>
  <form id="view-form">
    <input id="filter" type="search" placeholder="Filter by name" aria-label="Filter by name">
    <select id="sort" aria-label="Sort by">
      <option value="memory">Memory</option><option value="cpu">CPU time</option><option value="name">Name</option>
    </select>
    <label><input type="checkbox" id="paused"> Pause</label>
    <button id="copy" type="button">Copy table</button>
  </form>
  <p id="summary"></p>
  <table>
    <thead><tr><th>Name</th><th class="num">Id</th><th class="num">Memory (MB)</th><th class="num">CPU (s)</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
</main></body></html>"""

SORT_KEYS = {
    "memory": (lambda p: p.memory_mb, True),
    "cpu": (lambda p: p.cpu_seconds, True),
    "name": (lambda p: p.name.lower(), False),
}
SHOWN = 25


class Dashboard:
    def __init__(self, app: Application, document: Document, refresh_seconds: float):
        self.app, self.document, self.refresh_seconds = app, document, refresh_seconds
        self.lock = threading.Lock()          # rows/shown are read by callbacks and the worker
        self.rows: list = []
        self.shown: list = []
        self.refreshes = 0
        self.paused = False
        self.wake = threading.Event()         # set to refresh now (resume) or to stop
        self.stopped = threading.Event()
        doc = document
        doc.on("input", lambda _event: self.update_view(), element="filter")
        doc.on("change", lambda _event: self.update_view(), element="sort")
        doc.on("submit", lambda _event: self.update_view(), element="view-form")
        doc.on("change", self.on_pause, element="paused")
        doc.on("click", lambda _event: self.copy(), element="copy")
        app.on_shutdown(self.stop)

    # ----- the background refresh loop -----
    def start(self) -> threading.Thread:
        thread = threading.Thread(target=self._loop, name="process-refresh", daemon=True)
        thread.start()
        return thread

    def _loop(self) -> None:
        while not self.stopped.is_set():
            if not self.paused:
                try:
                    self.refresh()
                except NativeHTMLKitError:    # the window closed or the app is shutting down
                    return
            self.wake.wait(self.refresh_seconds)
            self.wake.clear()

    def refresh(self) -> None:
        rows = list_processes()               # the slow part: runs on this worker thread
        with self.lock:
            self.rows = rows
            self.refreshes += 1
            count = self.refreshes
        self.update_view()
        if not self.paused:                   # paused while collecting: keep showing "Paused"
            self.document.set_text("status", f"Updated {time.strftime('%H:%M:%S')} (refresh #{count})")

    def stop(self) -> None:
        self.stopped.set()
        self.wake.set()

    # ----- the view -----
    def update_view(self) -> None:
        needle = self.document.get_value("filter").strip().lower()
        key, descending = SORT_KEYS.get(self.document.get_value("sort"), SORT_KEYS["memory"])
        with self.lock:
            matching = [p for p in self.rows if needle in p.name.lower()]
            self.shown = sorted(matching, key=key, reverse=descending)[:SHOWN]
            shown, total = list(self.shown), len(self.rows)
            memory = sum(p.memory_mb for p in self.rows)
        cells = "".join(f'<tr><td>{html.escape(p.name)}</td><td class="num">{p.pid}</td>'
                        f'<td class="num">{p.memory_mb:,.1f}</td><td class="num">{p.cpu_seconds:,.1f}</td></tr>'
                        for p in shown)
        self.document.batch([
            {"op": "replace_children_html", "element": "rows", "html": cells},
            {"op": "set_text", "element": "summary",
             "text": f"Showing {len(shown)} of {total} processes, {memory:,.0f} MB in total"},
        ])

    def on_pause(self, event: dict) -> None:
        self.paused = bool(event.get("checked"))
        if self.paused:
            self.document.set_text("status", "Paused")
        else:
            self.wake.set()                   # refresh at once instead of after the interval

    def copy(self) -> None:
        with self.lock:
            lines = ["Name\tId\tMemoryMB\tCpu"] + [f"{p.name}\t{p.pid}\t{p.memory_mb}\t{p.cpu_seconds}"
                                                  for p in self.shown]
        try:
            self.app.set_clipboard_text("\n".join(lines))
            self.document.set_text("status", f"Copied {len(lines) - 1} rows")
        except RpcError:                      # -32001: no clipboard (for example headless runs)
            self.document.set_text("status", "The clipboard is not available in this session")


def build(app: Application, refresh_seconds: float = 3) -> Dashboard:
    window = app.open_html(PAGE, title="Process Dashboard", width=760, height=640)
    return Dashboard(app, window.document, refresh_seconds)


def main() -> None:
    # Parse inside main(): the host re-runs this script with the same arguments.
    parser = argparse.ArgumentParser(description="Live process dashboard")
    parser.add_argument("--refresh-seconds", type=float, default=3, help="refresh interval (1-3600)")
    args = parser.parse_args()
    if not 1 <= args.refresh_seconds <= 3600:
        parser.error("--refresh-seconds must be between 1 and 3600")
    with Application.start(name="Process Dashboard") as app:
        build(app, args.refresh_seconds).start()
        app.run()


if __name__ == "__main__":
    main()
```

- `start()` runs `_loop` in a daemon thread. The loop collects, updates the view and then waits
  on `self.wake` for `refresh_seconds`. Every SDK method is thread-safe, so the thread can update
  the page directly.
- `wake` doubles as a doorbell: unpausing sets it to refresh at once, and `stop()` sets it so the
  thread notices `stopped` without waiting for the interval. `app.on_shutdown(self.stop)` stops
  the thread when the application ends.
- `self.lock` protects `rows` and `shown`, which the thread and the event callbacks both use.
- The pause checkbox reads `event["checked"]` from the `change` event.
- When the window closes during a refresh, the next SDK call raises a `NativeHTMLKitError`
  (for example `StaleDocumentError`); the loop ends quietly.
- **Copy table** uses `app.set_clipboard_text` inside `try`/`except RpcError`: some sessions (for
  example headless test runs) have no clipboard and report error -32001.
- `--refresh-seconds` is a normal command-line option: `python dashboard.py --refresh-seconds 10`.
  The arguments are parsed in `main()`; the host re-runs the script with the same arguments.

## Test it without a screen

The repository checks every step headless. The core of the check for the final app:

```python
dashboard = example.build(app, refresh_seconds=1)
thread = dashboard.start()
# ... wait until dashboard.refreshes >= 1, then read the page back:
assert document.get_text("status").startswith("Updated ")
dashboard.on_pause({"checked": True})          # what the checkbox's change event does
assert document.get_text("status") == "Paused"
dashboard.stop()
thread.join(5)
```

See `process_dashboard` in
[tests/integration/example_checks.py](https://github.com/nativehtmlkit/nativehtmlkit-python/blob/main/tests/integration/example_checks.py)
for the complete version, and run a check of your own with
`NATIVEHTMLKIT_TEST_MODE=1 python -m nativehtmlkit run module:function` as shown in
[project scaffolding](../guides/project-scaffolding.md#test-it-headless).

## What you learned

- Render tables from data with escaped values; subscribe to `input`, `change` and `submit`.
- Keep slow work off the event thread with a worker thread, and update the page from it.
- Share state between the thread and callbacks under a lock; stop the thread on shutdown.
- Use a native service (the clipboard) with a fallback where it is unavailable.

## Where next

- [Background work](../guides/background-work.md): cancellation, quit confirmation and asyncio.
- [Live bitmaps](../guides/live-bitmaps.md): draw a memory chart next to the table.
- The [bulk rename tutorial](bulk-rename.md): files, dialogs and undo.
- [API reference](../API.md).
