"""Process viewer: a sortable, filterable table of running processes.

What it teaches
  * rendering plain Python data as an HTML table with escaped cells (``html.escape``)
  * the ``input`` event's ``value`` member (no extra round trip while typing)
  * sorting by clicking column headers, with ``aria-sort`` kept up to date
  * a status line with counts

The process list uses only the standard library: ``/proc`` on Linux and the Win32 API (through
``ctypes``) on Windows. In your own code, ``psutil`` is a good alternative.

Run:  uv run process_viewer.py
"""
from __future__ import annotations

import html
import os
import sys
import time
from dataclasses import dataclass

from nativehtmlkit import Application, Document


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
        name = _full_name(entry, stat[stat.index("(") + 1:stat.rindex(")")])
        fields = stat[stat.rindex(")") + 2:].split()
        cpu = (int(fields[11]) + int(fields[12])) / tick       # utime + stime
        memory = int(fields[21]) * page / 2**20                 # rss pages
        result.append(Process(name, int(entry), round(memory, 1), round(cpu, 1)))
    return result


def _full_name(pid: str, comm: str) -> str:
    """The kernel truncates comm to 15 characters; take the full name from argv[0] or the executable."""
    if len(comm) < 15:
        return comm
    candidates = []
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            candidates.append(handle.read().split(b"\0", 1)[0].decode("utf-8", errors="replace"))
    except OSError:
        pass
    try:
        candidates.append(os.readlink(f"/proc/{pid}/exe"))
    except OSError:                      # other users' processes: no access
        pass
    for candidate in candidates:
        base = os.path.basename(candidate)
        if base.startswith(comm):
            return base
    return comm


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


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { font-family: system-ui, sans-serif; margin: 16px; }
  .bar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
  #filter { flex: 1; padding: 6px 8px; font-size: 14px; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { text-align: left; padding: 4px 8px; border-bottom: 1px solid #ddd; }
  th { background: #eef1f6; }
  th button { all: unset; cursor: default; font-weight: 700; }
  td.num, th.num { text-align: right; }
  #status { color: #555; font-size: 13px; margin-top: 8px; }
</style></head>
<body>
  <div class="bar">
    <input id="filter" placeholder="Filter by name or id" aria-label="Filter">
    <button id="refresh">Refresh</button>
  </div>
  <table>
    <thead><tr id="headers">
      <th aria-sort="none" id="col-Name"><button id="sort-Name">Name</button></th>
      <th class="num" aria-sort="none" id="col-Id"><button id="sort-Id">PID</button></th>
      <th class="num" aria-sort="descending" id="col-MemoryMB"><button id="sort-MemoryMB">Memory (MB)</button></th>
      <th class="num" aria-sort="none" id="col-CpuSeconds"><button id="sort-CpuSeconds">CPU (s)</button></th>
    </tr></thead>
    <tbody id="rows"></tbody>
  </table>
  <p id="status"></p>
</body></html>"""

# Column id in the page -> Process attribute.
COLUMNS = {"Name": "name", "Id": "pid", "MemoryMB": "memory_mb", "CpuSeconds": "cpu_seconds"}
MAX_ROWS = 200


class ProcessViewer:
    def __init__(self, document: Document):
        self.document = document
        self.snapshot: list[Process] = []
        self.filter_text = ""
        self.sort_by, self.descending = "MemoryMB", True
        # The input event carries the control's current value: no get_value needed.
        document.on("input", self.on_filter, element="filter")
        document.on("click", self.on_header, element="headers")
        document.on("click", lambda _event: self.refresh(), element="refresh")
        self.refresh()

    def refresh(self) -> None:
        # Plain data only: the view never keeps OS handles.
        self.snapshot = list_processes()
        self.render()

    def visible(self) -> list[Process]:
        rows = self.snapshot
        needle = self.filter_text.lower()
        if needle:
            rows = [p for p in rows if needle in p.name.lower() or str(p.pid) == needle]
        attribute = COLUMNS[self.sort_by]
        key = (lambda p: p.name.lower()) if attribute == "name" else (lambda p: getattr(p, attribute))
        return sorted(rows, key=key, reverse=self.descending)[:MAX_ROWS]

    def render(self) -> None:
        rows = self.visible()
        cells = "".join(
            f'<tr><td>{html.escape(p.name)}</td><td class="num">{p.pid}</td>'
            f'<td class="num">{p.memory_mb:,.1f}</td><td class="num">{p.cpu_seconds:,.1f}</td></tr>' for p in rows)
        operations = [{"op": "replace_children_html", "element": "rows", "html": cells}]
        for column in COLUMNS:
            sort = "none" if column != self.sort_by else ("descending" if self.descending else "ascending")
            operations.append({"op": "set_attribute", "element": f"col-{column}", "name": "aria-sort", "value": sort})
        operations.append({"op": "set_text", "element": "status",
                           "text": f"Showing {len(rows)} of {len(self.snapshot)} processes. "
                                   f"Updated {time.strftime('%H:%M:%S')}."})
        self.document.batch(operations)

    def on_filter(self, event: dict) -> None:
        self.filter_text = str(event.get("value", "")).strip()
        self.render()

    def on_header(self, event: dict) -> None:
        column = event["element"].removeprefix("sort-")
        if column not in COLUMNS:
            return
        self.sort_by, self.descending = self.sort_column(column)
        self.render()

    def sort_column(self, column: str) -> tuple[str, bool]:
        """Clicking the sorted column flips the order; a new column starts descending (Name ascending)."""
        if column == self.sort_by:
            return column, not self.descending
        return column, column != "Name"


def build(app: Application) -> ProcessViewer:
    window = app.open_html(PAGE, title="Processes", width=760, height=620)
    return ProcessViewer(window.document)


def main() -> None:
    with Application.start(name="Process viewer") as app:
        build(app)
        app.run()


if __name__ == "__main__":
    main()
