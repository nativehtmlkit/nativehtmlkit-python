#!/usr/bin/env python3
"""Native desktop driver for the Python SDK GUI qualification (test tooling, stdlib only).

Runs INSIDE the interactive desktop session (KDE Plasma Wayland on Linux; the logged-in
RDP/console desktop on Windows). It launches gui_app.py through the SDK runner
(``python -m nativehtmlkit run``), performs each requested action with REAL OS input
(Linux: ydotool/uinput through KWin; Windows: SendInput), observes native windows
(KWin scripting / Win32) and accessibility (AT-SPI / UI Automation), and writes
``results.json`` with PASS/FAIL per check. SSH-only sessions cannot satisfy it.

usage: gui_driver.py --out DIR [--host PATH] [--python EXE] [--installed]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
WINDOWS = os.name == "nt"
SENTINEL = "nhkSENTINEL" + "5e1f02d4"
REQUIRED_APP_CHECKS = (
    "gui.window_appears", "gui.mouse_click_event", "gui.mouse_click_dom_update", "gui.keyboard_typing_value",
    "gui.keyboard_input_events", "gui.enter_submits_form", "gui.click_submit_button", "gui.submit_dom_update",
    "gui.accessibility_button_exposed", "gui.drag_moves_window", "gui.resize_driver_observed",
    "gui.resize_event_delivered", "gui.resize_state_updated", "gui.native_dialog_shown",
    "gui.native_dialog_cancel_result", "gui.before_close_veto_keeps_window", "gui.last_window_close_shuts_down",
    "gui.handles_stale_after_shutdown")


# --------------------------------------------------------------------------- Linux / KWin
class LinuxDesktop:
    KEYS = {"Enter": 28, "Escape": 1, "Tab": 15, "Alt": 56, "F4": 62}

    def __init__(self):
        self.lab = Path.home() / "lab/bin"
        subprocess.run([str(self.lab / "lab-input-init")], capture_output=True, timeout=20)
        self.a11y_previous = self._a11y_enabled()
        if self.a11y_previous is False:
            # What a screen reader does: ask toolkits (AccessKit) to expose AT-SPI. Restored in finish().
            self._set_a11y(True)

    def _a11y_enabled(self):
        out = subprocess.run(["busctl", "--user", "get-property", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status",
                              "IsEnabled"], capture_output=True, text=True)
        return {"b true": True, "b false": False}.get(out.stdout.strip())

    def _set_a11y(self, value: bool) -> None:
        subprocess.run(["busctl", "--user", "set-property", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status",
                        "IsEnabled", "b", "true" if value else "false"], capture_output=True)

    def finish(self) -> None:
        if self.a11y_previous is False:
            self._set_a11y(False)

    def kwin(self, js: str, wait: float = 0.5) -> list[str]:
        tag = "NHKPY" + uuid.uuid4().hex[:8]
        path = Path(tempfile.gettempdir()) / f"kwin-{tag}.js"
        path.write_text(js.replace("OUT(", f"print('{tag} ' + "))
        since = time.strftime("%Y-%m-%d %H:%M:%S")
        number = subprocess.check_output(["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.loadScript",
                                          str(path), tag], text=True).strip()
        subprocess.run(["qdbus6", "org.kde.KWin", f"/Scripting/Script{number}", "org.kde.kwin.Script.run"],
                       capture_output=True, check=True)
        time.sleep(wait)
        subprocess.run(["qdbus6", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting.unloadScript", tag],
                       capture_output=True)
        path.unlink(missing_ok=True)
        out = subprocess.run(["journalctl", "--user", "-q", "--since", since, "-o", "cat", "--no-pager"],
                             capture_output=True, text=True).stdout
        return [line.split(tag + " ", 1)[1] for line in out.splitlines() if tag + " " in line]

    def windows(self) -> list[dict]:
        lines = self.kwin(r"""var ws = workspace.windowList(); var r = [];
for (var i = 0; i < ws.length; i++) { var w = ws[i]; if (!w.normalWindow && !w.dialog) continue;
 r.push({caption: w.caption, pid: w.pid, x: w.frameGeometry.x, y: w.frameGeometry.y, w: w.frameGeometry.width,
 h: w.frameGeometry.height, cx: w.clientGeometry.x, cy: w.clientGeometry.y, cw: w.clientGeometry.width,
 ch: w.clientGeometry.height, active: w.active, dialog: w.dialog, modal: w.modal}); }
OUT(JSON.stringify(r));""")
        return json.loads(lines[-1]) if lines else []

    def find(self, title: str) -> dict | None:
        return next((w for w in self.windows() if title in w["caption"]), None)

    def activate(self, title: str) -> None:
        self.kwin("var ws = workspace.windowList(); for (var i=0;i<ws.length;i++){ if (ws[i].caption.indexOf(%s)>=0)"
                  "{ workspace.activeWindow = ws[i]; OUT('ok'); break; } }" % json.dumps(title), wait=0.3)

    def move(self, x: float, y: float) -> None:
        subprocess.run([str(self.lab / "lab-move"), str(int(round(x))), str(int(round(y)))], check=True, timeout=20)

    def click(self, x: float, y: float) -> None:
        subprocess.run([str(self.lab / "lab-click"), str(int(round(x))), str(int(round(y)))], check=True, timeout=20)
        time.sleep(0.3)

    def drag(self, x0, y0, x1, y1, steps: int = 20) -> None:
        self.move(x0, y0)
        self._ydotool("click", "0x40")
        time.sleep(0.25)
        px, py = int(round(x0)), int(round(y0))
        for i in range(1, steps + 1):
            nx, ny = int(round(x0 + (x1 - x0) * i / steps)), int(round(y0 + (y1 - y0) * i / steps))
            self._ydotool("mousemove", "-x", str(nx - px), "-y", str(ny - py))
            px, py = nx, ny
            time.sleep(0.03)
        time.sleep(0.25)
        self._ydotool("click", "0x80")
        time.sleep(0.6)

    def type(self, text: str) -> None:
        self._ydotool("type", "-d", "40", "--", text)
        time.sleep(0.4)

    def key(self, *names: str) -> None:
        codes = [self.KEYS[n] for n in names]
        self._ydotool("key", *[f"{c}:1" for c in codes], *[f"{c}:0" for c in reversed(codes)])
        time.sleep(0.3)

    def close(self, title: str) -> None:
        """KWin closeWindow(): the compositor's own close request (xdg_toplevel.close), as from the task bar."""
        self.kwin("var ws = workspace.windowList(); for (var i=0;i<ws.length;i++){ if (ws[i].caption.indexOf(%s)>=0)"
                  "{ ws[i].closeWindow(); OUT('ok'); break; } }" % json.dumps(title), wait=0.3)

    def _ydotool(self, *args: str) -> None:
        subprocess.run(["ydotool", *args], check=True, capture_output=True, timeout=30)

    def screenshot(self, path: Path) -> bool:
        subprocess.run(["spectacle", "-b", "-n", "-f", "-o", str(path)], capture_output=True, timeout=30)
        return path.exists() and path.stat().st_size > 0

    def client_point(self, window: dict, x: float, y: float, scale: float) -> tuple[float, float]:
        return window["cx"] + x, window["cy"] + y  # KWin logical coordinates == CSS px at scale 1

    def resize_handle(self, window: dict) -> tuple[float, float]:
        return window["x"] + window["w"] - 2, window["y"] + window["h"] - 2

    def accessibility(self, title: str, name: str) -> dict:
        code = r"""
import gi, json, sys
gi.require_version('Atspi', '2.0')
from gi.repository import Atspi
title, name = sys.argv[1], sys.argv[2]
def walk(node, depth=0):
    if node is None or depth > 40: return None
    try:
        if node.get_role() == Atspi.Role.PUSH_BUTTON and node.get_name() == name: return node
        for i in range(node.get_child_count()):
            hit = walk(node.get_child_at_index(i), depth + 1)
            if hit: return hit
    except Exception: return None
desktop = Atspi.get_desktop(0)
for i in range(desktop.get_child_count()):
    app = desktop.get_child_at_index(i)
    for j in range(app.get_child_count() if app else 0):
        frame = app.get_child_at_index(j)
        if frame is not None and title in (frame.get_name() or ''):
            hit = walk(frame)
            if hit:
                states = hit.get_state_set()
                print(json.dumps({'found': True, 'app': app.get_name(), 'frame': frame.get_name(),
                                  'focusable': states.contains(Atspi.StateType.FOCUSABLE)})); sys.exit(0)
            print(json.dumps({'found': False, 'app': app.get_name(), 'frame': frame.get_name()})); sys.exit(0)
print(json.dumps({'found': False, 'reason': 'window not in AT-SPI tree'}))
"""
        out = subprocess.run(["/usr/bin/python3", "-c", code, title, name], capture_output=True, text=True, timeout=60)
        try:
            return json.loads(out.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {"found": False, "reason": out.stderr[-400:]}

    def dialog_windows(self, known: set[str]) -> list[dict]:
        return [w for w in self.windows() if w["caption"] not in known]

    def image_name(self, pid: int) -> str:
        try:
            return os.path.basename(os.readlink(f"/proc/{pid}/exe"))
        except OSError:
            return ""


# --------------------------------------------------------------------------- Windows / Win32
class WindowsDesktop:
    VK = {"Enter": 0x0D, "Escape": 0x1B, "Tab": 0x09, "Alt": 0x12, "F4": 0x73}

    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.ctypes, self.wt = ctypes, wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        try:
            self.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per-monitor v2: physical pixels
        except AttributeError:
            pass
        self.user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
        self.user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        self.user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        self.user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        self.user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        self.user32.IsWindowVisible.argtypes = [wintypes.HWND]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", wintypes.DWORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        class UNION(ctypes.Union):
            _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("pad", ctypes.c_byte * 32)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", UNION)]
        self.INPUT = INPUT
        self.user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]

    def _send(self, *inputs) -> None:
        array = (self.INPUT * len(inputs))(*inputs)
        sent = self.user32.SendInput(len(inputs), array, self.ctypes.sizeof(self.INPUT))
        if sent != len(inputs):
            raise OSError(f"SendInput delivered {sent}/{len(inputs)} (error {self.ctypes.get_last_error()})")

    def _mouse(self, flags, x=0, y=0):
        item = self.INPUT(type=0)
        if flags & 0x8000:  # absolute: normalize over the virtual screen
            vx, vy = self.user32.GetSystemMetrics(76), self.user32.GetSystemMetrics(77)
            vw, vh = self.user32.GetSystemMetrics(78), self.user32.GetSystemMetrics(79)
            item.u.mi.dx = int(round((x - vx) * 65535 / max(vw - 1, 1)))
            item.u.mi.dy = int(round((y - vy) * 65535 / max(vh - 1, 1)))
            flags |= 0x4000  # VIRTUALDESK
        item.u.mi.dwFlags = flags
        return item

    def move(self, x, y):
        self._send(self._mouse(0x0001 | 0x8000, x, y))
        time.sleep(0.05)

    def covering_window(self, x, y, expected_hwnd: int) -> str | None:
        """Caption of the top-level window under (x, y) if it is not ``expected_hwnd``."""
        wt = self.wt
        self.user32.WindowFromPoint.argtypes = [wt.POINT]
        self.user32.WindowFromPoint.restype = wt.HWND
        self.user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
        self.user32.GetAncestor.restype = wt.HWND
        top = self.user32.GetAncestor(self.user32.WindowFromPoint(wt.POINT(int(x), int(y))), 2) or 0
        if int(top) == expected_hwnd:
            return None
        title = self.ctypes.create_unicode_buffer(256)
        self.user32.GetWindowTextW(top, title, 256)
        return title.value or f"hwnd {int(top)}"

    def click(self, x, y):
        self.move(x, y)
        self._send(self._mouse(0x0002), self._mouse(0x0004))
        time.sleep(0.3)

    def drag(self, x0, y0, x1, y1, steps=20):
        self.move(x0, y0)
        self._send(self._mouse(0x0002))
        time.sleep(0.2)
        for i in range(1, steps + 1):
            self.move(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
            time.sleep(0.02)
        time.sleep(0.2)
        self._send(self._mouse(0x0004))
        time.sleep(0.6)

    def _key(self, vk=0, scan=0, flags=0):
        item = self.INPUT(type=1)
        item.u.ki.wVk, item.u.ki.wScan, item.u.ki.dwFlags = vk, scan, flags
        return item

    def type(self, text):
        for char in text:
            for unit in char.encode("utf-16-le").decode("utf-16-le"):
                code = ord(unit)
                self._send(self._key(scan=code, flags=0x0004), self._key(scan=code, flags=0x0004 | 0x0002))
                time.sleep(0.02)
        time.sleep(0.4)

    def key(self, *names):
        codes = [self.VK[n] for n in names]
        self._send(*[self._key(vk=c) for c in codes], *[self._key(vk=c, flags=0x0002) for c in reversed(codes)])
        time.sleep(0.3)

    def windows(self):
        ctypes, wt = self.ctypes, self.wt
        found = []

        @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        def callback(hwnd, _):
            if not self.user32.IsWindowVisible(hwnd):
                return True
            length = self.user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length + 1)
            self.user32.GetWindowTextW(hwnd, title, length + 1)
            cls = ctypes.create_unicode_buffer(256)
            self.user32.GetClassNameW(hwnd, cls, 256)
            rect, client, origin, pid = wt.RECT(), wt.RECT(), wt.POINT(0, 0), wt.DWORD()
            self.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            self.user32.GetClientRect(hwnd, ctypes.byref(client))
            self.user32.ClientToScreen(hwnd, ctypes.byref(origin))
            self.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if title.value:
                found.append({"caption": title.value, "class": cls.value, "pid": pid.value, "hwnd": int(hwnd or 0),
                              "x": rect.left, "y": rect.top, "w": rect.right - rect.left, "h": rect.bottom - rect.top,
                              "cx": origin.x, "cy": origin.y, "cw": client.right, "ch": client.bottom})
            return True
        self.user32.EnumWindows(callback, 0)
        return found

    def find(self, title):
        return next((w for w in self.windows() if title in w["caption"]), None)

    def activate(self, title):
        window = self.find(title)
        if window:  # a real click on the caption (SetForegroundWindow is refused for background processes)
            self.click(window["x"] + window["w"] // 2, window["y"] + max(8, (window["cy"] - window["y"]) // 2))

    def close(self, title):
        self.activate(title)
        time.sleep(0.3)
        self.key("Alt", "F4")

    def screenshot(self, path: Path) -> bool:
        script = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing; "
                  "$b=[System.Windows.Forms.SystemInformation]::VirtualScreen; "
                  "$i=New-Object System.Drawing.Bitmap $b.Width,$b.Height; $g=[System.Drawing.Graphics]::FromImage($i); "
                  "$g.CopyFromScreen($b.Left,$b.Top,0,0,$i.Size); $i.Save('%s'); $g.Dispose(); $i.Dispose()") % str(path)
        subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, timeout=60)
        return path.exists() and path.stat().st_size > 0

    def client_point(self, window, x, y, scale):
        return window["cx"] + x * scale, window["cy"] + y * scale

    def resize_handle(self, window):
        return window["x"] + window["w"] - 4, window["y"] + window["h"] - 4

    def accessibility(self, title, name):
        script = r"""
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, '%s', [System.Windows.Automation.PropertyConditionFlags]::IgnoreCase)
$win = $null
foreach ($w in $root.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)) { if ($w.Current.Name -like '*%s*') { $win = $w; break } }
if (-not $win) { '{"found": false, "reason": "window not in UIA tree"}'; exit }
$hit = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $cond)
if ($hit) { '{"found": true, "control_type": "' + $hit.Current.ControlType.ProgrammaticName + '", "focusable": ' + $hit.Current.IsKeyboardFocusable.ToString().ToLower() + '}' }
else { '{"found": false, "reason": "button not found"}' }
""" % (name.replace("'", "''"), title.replace("'", "''"))
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=90)
        try:
            return json.loads(out.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return {"found": False, "reason": out.stderr[-400:]}

    def dialog_windows(self, known):
        return [w for w in self.windows() if w["caption"] not in known and w["class"] == "#32770"]

    def finish(self) -> None:
        pass

    def image_name(self, pid: int) -> str:
        k = self.ctypes.WinDLL("kernel32", use_last_error=True)
        k.OpenProcess.restype = self.wt.HANDLE
        handle = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            size = self.wt.DWORD(1024)
            buffer = self.ctypes.create_unicode_buffer(1024)
            if k.QueryFullProcessImageNameW(handle, 0, buffer, self.ctypes.byref(size)):
                return os.path.basename(buffer.value)
            return ""
        finally:
            k.CloseHandle(handle)


# --------------------------------------------------------------------------- orchestration
def leftovers(marker: str, launcher_pid: int) -> list:
    """Processes of THIS run only: Linux by the env marker; Windows by the marker on the command
    line or descent from our launcher. Never by executable path (another agent may run the same host)."""
    found = []
    if sys.platform.startswith("linux"):
        needle = f"NHK_IT_MARKER={marker}".encode()
        for entry in Path("/proc").iterdir():
            if entry.name.isdigit() and int(entry.name) != os.getpid():
                try:
                    if needle in (entry / "environ").read_bytes().split(b"\0"):
                        found.append(int(entry.name))
                except OSError:
                    pass
    else:
        script = ("Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID } | ForEach-Object { "
                  "'{0}|{1}|{2}' -f $_.ProcessId, $_.ParentProcessId, $_.CommandLine }")
        out = subprocess.run(["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, timeout=60)
        table = {}
        for line in out.stdout.splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
                table[int(parts[0])] = (int(parts[1]), parts[2])
        ours = {launcher_pid}
        changed = True
        while changed:
            changed = False
            for pid, (parent, _cmd) in table.items():
                if parent in ours and pid not in ours:
                    ours.add(pid)
                    changed = True
        found = sorted(pid for pid, (_parent, cmd) in table.items()
                       if pid != os.getpid() and (pid in ours or marker in cmd))
    return found


def perform(desk, request: dict, out: Path, state: dict) -> dict:
    action = request["action"]
    ack = {"ack": request["id"]}
    try:
        if action == "locate":
            deadline = time.monotonic() + request.get("wait", 20)
            window = None
            while time.monotonic() < deadline and window is None:
                window = desk.find(request["title"])
                if window is None:
                    time.sleep(0.3)
            ack.update(found=window is not None, window=window)
            if window:
                state["title"] = request["title"]
        elif action == "screenshot":
            path = out / "screenshots" / f"{request['name']}.png"
            path.parent.mkdir(exist_ok=True)
            ack["saved"] = desk.screenshot(path)
        elif action == "click":
            desk.activate(request["title"])
            window = desk.find(request["title"])
            x, y = desk.client_point(window, request["x"], request["y"], request.get("scale", 1.0))
            covered = desk.covering_window(x, y, window.get("hwnd", 0)) if WINDOWS else None
            if covered:
                ack["error"] = f"click target covered by another window: {covered!r}"
            desk.click(x, y)
            ack.update(done=True, at=[x, y])
        elif action == "type":
            desk.type(request["text"])
            ack["done"] = True
        elif action == "key":
            desk.key(request["key"])
            ack["done"] = True
        elif action == "drag":
            desk.activate(request["title"])
            before = desk.find(request["title"])
            x, y = desk.client_point(before, request["x"], request["y"], request.get("scale", 1.0))
            desk.drag(x, y, x + request["dx"], y + request["dy"])
            time.sleep(0.4)
            after = desk.find(request["title"])
            ack.update(before=before, after=after,
                       resized=after["w"] > before["w"] and after["h"] > before["h"],
                       moved=(after["x"], after["y"]) != (before["x"], before["y"]) and (after["w"], after["h"]) == (before["w"], before["h"]))
        elif action == "resize":
            desk.activate(request["title"])
            before = desk.find(request["title"])
            x, y = desk.resize_handle(before)
            desk.drag(x, y, x + request["dx"], y + request["dy"])
            after = desk.find(request["title"])
            ack.update(before=before, after=after, resized=after["w"] > before["w"] and after["h"] > before["h"])
        elif action == "dialog-prepare":
            state["known"] = {w["caption"] for w in desk.windows()}
            ack["done"] = True
        elif action == "dialog-cancel":
            known = state.get("known") or {w["caption"] for w in desk.windows()}
            deadline = time.monotonic() + 45
            dialog = None
            while time.monotonic() < deadline and dialog is None:
                named = desk.find(request["title_hint"])
                fresh = desk.dialog_windows(known)
                dialog = named or (fresh[0] if fresh else None)
                if dialog is None:
                    time.sleep(0.4)
            ack.update(seen=dialog is not None, caption=dialog["caption"] if dialog else None)
            if dialog:
                time.sleep(1.0)
                path = out / "screenshots" / "04-native-dialog.png"
                path.parent.mkdir(exist_ok=True)
                desk.screenshot(path)
                desk.activate(dialog["caption"])
                time.sleep(0.4)
                desk.key("Escape")
                gone_deadline = time.monotonic() + 15
                while time.monotonic() < gone_deadline and desk.find(dialog["caption"]):
                    time.sleep(0.3)
                ack["gone"] = desk.find(dialog["caption"]) is None
        elif action == "a11y":
            ack.update(desk.accessibility(request["title"], request["name"]))
            ack["detail"] = dict(ack)
        elif action == "native-close":
            desk.close(request["title"])
            time.sleep(0.8)
            ack["done"] = True
        else:
            ack["error"] = f"unknown action {action}"
    except Exception as error:  # reported to the app, which fails the dependent check
        ack["error"] = f"{type(error).__name__}: {error}"
    return ack


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--host", help="host executable (default: NATIVEHTMLKIT_HOST_BINARY or the installed wheel's)")
    parser.add_argument("--python", default=sys.executable, help="interpreter that runs the SDK app")
    parser.add_argument("--installed", action="store_true", help="use the installed nativehtmlkit, not ./src")
    parser.add_argument("--timeout", type=float, default=420)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists():
        shutil.rmtree(out)
    (out / "screenshots").mkdir(parents=True)
    desk = WindowsDesktop() if WINDOWS else LinuxDesktop()
    # Pre-flight: another NativeHTMLKit app on this shared desktop would steal focus/input.
    foreign = [{"caption": w["caption"], "pid": w["pid"]} for w in desk.windows()
               if desk.image_name(w["pid"]).lower().startswith("nativehtmlkit-host")]
    if foreign:
        desk.finish()
        (out / "results.json").write_text(json.dumps({
            "platform": "windows-interactive" if WINDOWS else "linux-kde-wayland", "blocked": True,
            "reason": f"foreign NativeHTMLKit window(s) on the shared desktop: {foreign}", "checks": {},
            "failed": [], "session_env": {}}, indent=2), encoding="utf-8")
        print(json.dumps({"blocked": True, "foreign": foreign}))
        return 3
    marker = uuid.uuid4().hex[:10]
    session = f"gui:{marker}"
    records, acks = out / "records.jsonl", out / "acks.jsonl"
    env = {k: v for k, v in os.environ.items() if not k.startswith("UI4ME_")}
    env.update({"NHK_IT_OUT": str(records), "NHK_GUI_ACKS": str(acks), "NHK_IT_MARKER": marker,
                "NHK_IT_SENTINEL": SENTINEL, "NATIVEHTMLKIT_DIAGNOSTICS": "trace",
                "NATIVEHTMLKIT_DIAGNOSTIC_SESSION_ID": session, "NATIVEHTMLKIT_DIAGNOSTICS_DIR": str(out / "diag"),
                "NATIVEHTMLKIT_HOST_LOG": str(out / "host-stderr.jsonl"),
                "PYTHONPATH": os.pathsep.join(([] if args.installed else [str(ROOT / "src")]) + [str(HERE)])})
    env.pop("NATIVEHTMLKIT_TEST_MODE", None)
    if args.host:
        env["NATIVEHTMLKIT_HOST_BINARY"] = str(Path(args.host).resolve())
    if not WINDOWS:
        env.update(QT_QPA_PLATFORM="wayland", GDK_BACKEND="wayland")
        env.pop("DISPLAY", None)
    version = subprocess.run([args.python, "-m", "nativehtmlkit", "version"], env=env, capture_output=True, text=True)
    provenance = json.loads(version.stdout) if version.returncode == 0 else {"error": version.stderr[-500:]}
    host_path = (provenance.get("host") or {}).get("path") or ""
    command = [args.python, "-m", "nativehtmlkit", "run", "gui_app:main", "--name", f"NHK PyGUI {marker}"]
    started = time.monotonic()
    log = (out / "launcher-stderr.txt").open("wb")
    proc = subprocess.Popen(command, cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT)
    done, state, timed_out = set(), {}, False
    try:
        while proc.poll() is None:
            if time.monotonic() - started > args.timeout:
                timed_out = True
                break
            if records.exists():
                for line in records.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if record.get("kind") == "request" and record["id"] not in done:
                        done.add(record["id"])
                        ack = perform(desk, record, out, state)
                        with acks.open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(ack, default=repr) + "\n")
            time.sleep(0.1)
        if timed_out:
            if state.get("title"):
                path = out / "screenshots" / "99-timeout.png"
                desk.screenshot(path)
            proc.kill()
        rc = proc.wait(30)
    finally:
        log.close()
        desk.finish()
    seconds = round(time.monotonic() - started, 2)
    remaining = []
    for _ in range(50):
        remaining = leftovers(marker, proc.pid)
        if not remaining:
            break
        time.sleep(0.1)
    window_left = desk.find(f"NHK PyGUI {marker}") is not None
    cleaned = []
    if remaining:  # leave the shared desktop clean before the lock is released (still a FAIL)
        import signal as _signal
        for pid in remaining:
            try:
                os.kill(pid, _signal.SIGKILL if hasattr(_signal, "SIGKILL") else _signal.SIGTERM)
                cleaned.append(pid)
            except OSError:
                pass
    checks = {}
    lines = [json.loads(l) for l in records.read_text(encoding="utf-8").splitlines() if l.strip()] if records.exists() else []
    for record in lines:
        if record.get("kind") == "check":
            if record["name"] not in checks or checks[record["name"]]["status"] == "pass":
                checks[record["name"]] = record
    sdk = []
    for file in sorted((out / "diag").glob("python-*.jsonl")):
        sdk += [json.loads(l) for l in file.read_text(encoding="utf-8").splitlines() if l.strip()]
    host_lines = (out / "host-stderr.jsonl").read_text(encoding="utf-8", errors="replace") if (out / "host-stderr.jsonl").exists() else ""
    host_sessions = set()
    for line in host_lines.splitlines():
        try:
            host_sessions.add(json.loads(line).get("diagnostic_session_id"))
        except ValueError:
            pass
    zip_path = out / "support.zip"
    export = subprocess.run([args.python, "-m", "nativehtmlkit", "support", str(zip_path), "--session", session],
                            env=env, capture_output=True, text=True)
    blob = b""
    if zip_path.exists():
        import zipfile
        with zipfile.ZipFile(zip_path) as archive:
            blob = b"".join(archive.read(n) for n in archive.namelist())
            zip_names = archive.namelist()
    else:
        zip_names = []
    typed_seen = any(r["event"] == "host.notification" and r["context"].get("event_type") == "input" for r in sdk)
    driver_checks = {
        "gui.launcher_exit_0": rc == 0 and not timed_out,
        "gui.no_orphan_processes": not remaining,
        "gui.no_window_left": not window_left,
        "gui.on_shutdown_ran": any(r.get("name") == "on_shutdown_ran" for r in lines),
        "privacy.typed_sentinel_absent_from_sdk_records": bool(sdk) and SENTINEL not in json.dumps(sdk),
        "privacy.typed_sentinel_absent_from_host_stderr": bool(host_lines) and SENTINEL not in host_lines,
        "privacy.typed_sentinel_absent_from_support_zip": export.returncode == 0 and bool(blob) and SENTINEL.encode() not in blob,
        "privacy.support_zip_only_sanitized_files": sorted(zip_names) == ["manifest.json", "timeline.jsonl"],
        "diagnostics.real_input_events_recorded": typed_seen,
        "diagnostics.session_reached_host": host_sessions == {session},
    }
    for name in REQUIRED_APP_CHECKS:
        if name not in checks:
            checks[name] = {"name": name, "status": "fail", "error": "scenario never reached this check"}
    for name, ok in driver_checks.items():
        checks[name] = {"name": name, "status": "pass" if ok else "fail"}
    result = {
        "platform": "windows-interactive" if WINDOWS else "linux-kde-wayland", "session_env": {
            k: os.environ.get(k) for k in ("XDG_SESSION_TYPE", "WAYLAND_DISPLAY", "XDG_CURRENT_DESKTOP", "SESSIONNAME", "USERNAME")},
        "python": subprocess.run([args.python, "-c", "import sys;print(sys.version.split()[0])"], capture_output=True,
                                 text=True).stdout.strip(),
        "provenance": provenance, "rc": rc, "timed_out": timed_out, "seconds": seconds, "leftovers": remaining,
        "sentinel_in_raw_host_log": SENTINEL in host_lines, "killed_leftovers": cleaned,
        "atspi_is_enabled_after_run": desk._a11y_enabled() if hasattr(desk, "_a11y_enabled") else None,
        "atspi_is_enabled_before_run": getattr(desk, "a11y_previous", None),
        "checks": checks, "failed": sorted(k for k, v in checks.items() if v["status"] != "pass"),
        "observations": [r for r in lines if r.get("kind") == "info"],
    }
    (out / "results.json").write_text(json.dumps(result, indent=2, default=repr), encoding="utf-8")
    print(json.dumps({"checks": len(checks), "failed": result["failed"], "rc": rc, "seconds": seconds}, indent=1))
    return 0 if not result["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
