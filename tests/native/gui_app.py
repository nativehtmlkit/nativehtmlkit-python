"""Native GUI qualification app, run by the real host via ``python -m nativehtmlkit run gui_app:main``.

The app owns the BEHAVIOUR ASSERTIONS: it asks the desktop driver (gui_driver.py) for one
real OS input action at a time (request/ack JSON lines) and then checks what the SDK
observed through the host: events, DOM values and window state. Screenshots are only
supporting evidence. Element positions come from the host (``get_rect``, logical px
relative to the client area); the driver maps them to the screen.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "integration"))
from it_support import Guard, check, emit  # noqa: E402

TITLE = "NHK PyGUI " + os.environ.get("NHK_IT_MARKER", "x")
SENTINEL = os.environ.get("NHK_IT_SENTINEL", "")
TYPED = "Hello nhk 123 " + SENTINEL
HTML = """<!doctype html><html><head><style>
body { margin: 0; font-family: sans-serif; background: #f4f6fa; }
main { padding: 16px; }
#dragzone { width: 260px; height: 54px; background: #46689a; color: white; margin-top: 12px; }
input { width: 320px; height: 30px; font-size: 16px; }
button { height: 36px; min-width: 110px; margin: 6px 4px; font-size: 15px; }
</style></head><body><main>
<div id="dragzone" data-ui4me-drag>Drag window here</div>
<form id="login"><label for="field">Text</label><br>
<input id="field" name="field" type="text" value="">
<button id="submit" type="submit">Submit</button></form>
<button id="clicker" type="button">Click me</button> <span id="count">0</span>
<p id="status" role="status">Waiting</p>
</main>
<div id="grip" data-ui4me-resize="se"
     style="position:fixed;right:0;bottom:0;width:22px;height:22px;background:#9ab"></div>
</body></html>"""


class Driver:
    """Request one real input action from the desktop driver and wait for its acknowledgement."""

    def __init__(self):
        self.acks = Path(os.environ["NHK_GUI_ACKS"])
        self.next_id = 0

    def __call__(self, action: str, timeout: float = 60, **args) -> dict:
        self.next_id += 1
        rid = self.next_id
        emit("request", id=rid, action=action, **args)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.acks.exists():
                for line in self.acks.read_text(encoding="utf-8").splitlines():
                    if line.strip():
                        ack = json.loads(line)
                        if ack.get("ack") == rid:
                            return ack
            time.sleep(0.05)
        return {"ack": rid, "error": "driver timeout"}


def wait_for(predicate, timeout=8.0, step=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(step)
    return predicate()


def main(app):
    driver = Driver()
    # Frameless: Core honours data-ui4me-drag / data-ui4me-resize only without decorations.
    window = app.open_html(HTML, title=TITLE, width=760, height=520, decorations=False)
    document = window.document
    seen = {"click": 0, "input": 0, "submit": 0, "window": []}
    lock = threading.Lock()

    def count(kind):
        def handler(_event):
            with lock:
                seen[kind] += 1
            if kind == "click":
                document.set_text("count", str(seen["click"]))
            if kind == "submit":
                document.set_text("status", f"Submitted {seen['submit']}")
        return handler
    document.on("click", count("click"), element="clicker")
    document.on("input", count("input"), element="field")
    document.on("submit", count("submit"), element="login")
    app.on_window_event(lambda p: seen["window"].append(p.get("type")))
    veto = {"remaining": 1, "asked": 0}

    def before_close():
        veto["asked"] += 1
        if veto["remaining"]:
            veto["remaining"] -= 1
            emit("info", name="close_vetoed_once")
            return False
        return True
    window.on_before_close(before_close)

    def rect(element):
        r = document.command("get_rect", element=element)["rect"]
        return {"x": r["x"] + r["width"] / 2, "y": r["y"] + r["height"] / 2}

    def scenario():
        deadline = time.monotonic() + 30
        while not app._ready and time.monotonic() < deadline:
            time.sleep(0.05)
        scale = window.state().get("scale_factor") or 1.0
        emit("info", name="scale_factor", value=scale)
        with Guard("gui.window_appears"):
            located = driver("locate", title=TITLE)
            check("gui.window_appears", located.get("found") is True, window=located.get("window"))
            driver("screenshot", name="01-ready")
        with Guard("gui.mouse_click"):
            ack = driver("click", title=TITLE, scale=scale, **rect("clicker"))
            check("gui.mouse_click_event", wait_for(lambda: seen["click"] >= 1), clicks=seen["click"],
                  ack_error=ack.get("error"))
            check("gui.mouse_click_dom_update", document.get_text("count") == str(seen["click"]))
        with Guard("gui.keyboard"):
            driver("click", title=TITLE, scale=scale, **rect("field"))
            focused = wait_for(lambda: (document.focused_element() or {}).get("element") == "field"
                               or (document.focused_element() or {}).get("id") == "field", 3)
            emit("info", name="focused_after_click", value=document.focused_element())
            ack = driver("type", text=TYPED)
            value = wait_for(lambda: document.get_value("field") == TYPED, 10)
            check("gui.keyboard_typing_value", value, typed_len=len(TYPED),
                  got_len=len(document.get_value("field")), ack_error=ack.get("error"))
            check("gui.keyboard_input_events", seen["input"] >= 1, inputs=seen["input"])
            check("gui.click_focused_input", bool(focused))
        with Guard("gui.form_submit"):
            driver("key", key="Enter")
            check("gui.enter_submits_form", wait_for(lambda: seen["submit"] >= 1), submits=seen["submit"])
            driver("click", title=TITLE, scale=scale, **rect("submit"))
            check("gui.click_submit_button", wait_for(lambda: seen["submit"] >= 2), submits=seen["submit"])
            check("gui.submit_dom_update", document.get_text("status") == f"Submitted {seen['submit']}")
            driver("screenshot", name="02-after-submit")
        with Guard("gui.accessibility"):
            a11y = driver("a11y", title=TITLE, name="Click me")
            check("gui.accessibility_button_exposed", a11y.get("found") is True, detail=a11y.get("detail"))
        with Guard("gui.drag"):
            before_events = len(seen["window"])
            ack = driver("drag", title=TITLE, scale=scale, dx=140, dy=90, **rect("dragzone"))
            check("gui.drag_moves_window", ack.get("moved") is True, before=ack.get("before"), after=ack.get("after"))
            emit("info", name="window_events_after_drag", value=seen["window"][before_events:])
        with Guard("gui.resize"):
            size_before = (window.state()["width"], window.state()["height"])
            before_events = len(seen["window"])
            ack = driver("drag", title=TITLE, scale=scale, dx=120, dy=70, expect="resize", **rect("grip"))
            resized = wait_for(lambda: "resized" in seen["window"][before_events:], 5)
            size_after = (window.state()["width"], window.state()["height"])
            check("gui.resize_driver_observed", ack.get("resized") is True, before=ack.get("before"), after=ack.get("after"))
            emit("info", name="window_events_after_resize", value=seen["window"][before_events:])
            check("gui.resize_event_delivered", bool(resized), events=seen["window"][before_events:])
            check("gui.resize_state_updated", size_after[0] > size_before[0] and size_after[1] > size_before[1],
                  before=size_before, after=size_after)
            driver("screenshot", name="03-after-resize")
        with Guard("gui.native_dialog"):
            driver("dialog-prepare")
            future = window.open_files(title="NHK PyGUI dialog", wait=False)
            ack = driver("dialog-cancel", title_hint="NHK PyGUI dialog", main_title=TITLE, timeout=90)
            check("gui.native_dialog_shown", ack.get("seen") is True, caption=ack.get("caption"))
            try:
                result = future.result(30)
                check("gui.native_dialog_cancel_result", isinstance(result, dict), result=result)
            except Exception as error:
                check("gui.native_dialog_cancel_result", False, error=type(error).__name__, message=str(error)[:200])
        with Guard("gui.close"):
            ack = driver("native-close", title=TITLE)
            asked = wait_for(lambda: veto["asked"] >= 1, 10)
            time.sleep(0.5)
            still = driver("locate", title=TITLE, wait=2)
            check("gui.before_close_veto_keeps_window", bool(asked) and still.get("found") is True and not window.closed,
                  asked=veto["asked"], found=still.get("found"))
            emit("info", name="scenario_done", seen={k: v for k, v in seen.items() if k != "window"})
            driver("native-close", title=TITLE)  # allowed: last window -> quit -> shutdown

    def on_shutdown():
        # Runs in run()'s thread after the final events were delivered (the scenario
        # thread may already be gone because the process is exiting).
        # Core 1.0.x: closing the LAST window goes straight to app.shutdown without a
        # window.event "closed" (host/mod.rs last_window path); assert what is specified.
        check("gui.last_window_close_shuts_down", veto["asked"] >= 2 and "close_requested" in seen["window"],
              asked=veto["asked"], events=seen["window"][-5:])
        # app.shutdown implies every window is closed (protocol v1 §7): handles are stale now.
        check("gui.handles_stale_after_shutdown", window.closed and document._retired)
        emit("info", name="closed_event_for_last_window", value="closed" in seen["window"])
        emit("info", name="on_shutdown_ran")
    app.on_shutdown(on_shutdown)
    emit("ready", scenario="gui", title=TITLE)
    threading.Thread(target=scenario, name="gui-scenario", daemon=True).start()
