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
