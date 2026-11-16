"""Focus timer: application lifecycle, quit confirmation and saving state on shutdown.

What it teaches
  * a ``setup(app)`` entry point that works with BOTH launch styles:
      python examples/focus_timer.py                         (Application.start)
      cd examples && python -m nativehtmlkit run focus_timer:setup   (host-first runner)
  * ``on_before_quit``: veto a quit while the timer runs and ask with an HTML <dialog>
  * ``on_shutdown``: save statistics after the host shut down (no more RPC is possible then)
  * ``Window.request_attention`` (where the platform supports it) and ``Window.set(title=...)``
  * a ticking background thread that stops with the application
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from nativehtmlkit import Application, NativeHTMLKitError, RpcError, Window

APP_ID = "org.nativehtmlkit.examples.focus_timer"

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { margin:0; font:15px sans-serif; background:#1e2233; color:#eef0f7; text-align:center; }
  main { padding:28px 20px; }
  #clock { font-size:64px; font-variant-numeric:tabular-nums; margin:12px 0; }
  form { display:flex; gap:8px; justify-content:center; align-items:center; }
  input { width:60px; padding:6px; }
  button { padding:7px 14px; border:0; border-radius:6px; background:#5b7cfa; color:#fff; cursor:pointer; }
  button.secondary { background:#3a4058; }
  #sessions { color:#a8afc6; margin-top:14px; }
  dialog { border:0; border-radius:10px; padding:20px; background:#2b3047; color:#eef0f7; }
  .running #clock { color:#8ef0b6; }
</style></head>
<body id="body"><main>
  <h1>Focus timer</h1>
  <div id="clock">25:00</div>
  <form id="controls">
    <label>Minutes <input id="minutes" type="number" min="1" max="120" value="25"></label>
    <button id="start" type="submit">Start</button>
    <button id="pause" type="button" class="secondary">Pause</button>
    <button id="reset" type="button" class="secondary">Reset</button>
  </form>
  <p id="sessions">Completed sessions: 0</p>
  <dialog id="confirm-quit"><p>The timer is still running. Quit anyway?</p>
    <button id="quit-anyway">Quit</button> <button id="keep" class="secondary">Keep running</button></dialog>
</main></body></html>"""


class FocusTimer:
    def __init__(self, app: Application, window: Window, stats_file: Path):
        self.app, self.window, self.document = app, window, window.document
        self.stats_file = stats_file
        self.stats = self._load_stats()
        self.saved_stats = dict(self.stats)
        self.remaining = 25 * 60.0
        self.deadline: float | None = None          # monotonic time when the timer ends
        self.allow_quit = False
        self.stopped = threading.Event()
        doc = self.document
        doc.on("submit", lambda _e: self.start(self._minutes() * 60), element="controls")
        doc.on("click", lambda _e: self.pause(), element="pause")
        doc.on("click", lambda _e: self.reset(), element="reset")
        doc.on("click", lambda _e: self.quit_anyway(), element="quit-anyway")
        doc.on("click", lambda _e: doc.close_dialog("confirm-quit", "keep"), element="keep")
        app.on_before_quit(self.may_quit)
        app.on_shutdown(self.on_shutdown)
        threading.Thread(target=self._tick, name="timer-tick", daemon=True).start()
        self.show()

    @property
    def running(self) -> bool:
        return self.deadline is not None

    def start(self, seconds: float) -> None:
        self.remaining = float(seconds)
        self.deadline = time.monotonic() + self.remaining
        self.document.add_class("body", "running")
        self.show()

    def pause(self) -> None:
        if self.running:
            self.remaining = max(0.0, self.deadline - time.monotonic())
            self.deadline = None
            self.document.remove_class("body", "running")

    def reset(self) -> None:
        self.deadline = None
        self.remaining = self._minutes() * 60.0
        self.document.remove_class("body", "running")
        self.show()

    def show(self) -> None:
        left = max(0.0, self.deadline - time.monotonic()) if self.running else self.remaining
        minutes, seconds = divmod(int(round(left)), 60)
        self.document.set_text("clock", f"{minutes:02d}:{seconds:02d}")
        self.window.set(title=f"{minutes:02d}:{seconds:02d} — Focus timer" if self.running else "Focus timer")

    def finish(self) -> None:
        self.deadline, self.remaining = None, 0.0
        self.stats["completed"] += 1
        self.document.remove_class("body", "running")
        self.document.set_text("sessions", f"Completed sessions: {self.stats['completed']}")
        self.show()
        try:
            self.window.request_attention("informational")
        except RpcError:
            pass                                   # not available (headless, some compositors)

    def _tick(self) -> None:
        while not self.stopped.wait(0.25):
            if not self.running:
                continue
            try:
                if time.monotonic() >= self.deadline:
                    self.finish()
                else:
                    self.show()
            except NativeHTMLKitError:
                return                             # window gone / shutting down

    # ----- lifecycle -----
    def may_quit(self) -> bool:
        """The host asks before quitting (last window closed, or request_quit())."""
        if self.running and not self.allow_quit:
            self.document.show_dialog("confirm-quit")
            return False
        return True

    def quit_anyway(self) -> None:
        self.allow_quit = True
        self.document.close_dialog("confirm-quit", "quit")
        self.app.request_quit()                    # asks may_quit() again, which now allows it

    def on_shutdown(self) -> None:
        # Runs in the thread that called app.run(), after the host shut down: plain Python only.
        self.stopped.set()
        if self.stats == self.saved_stats:
            return                                 # nothing new to save
        self.stats_file.parent.mkdir(parents=True, exist_ok=True)
        self.stats_file.write_text(json.dumps(self.stats), encoding="utf-8")

    def _load_stats(self) -> dict:
        try:
            return {"completed": int(json.loads(self.stats_file.read_text(encoding="utf-8"))["completed"])}
        except (OSError, ValueError, KeyError, TypeError):
            return {"completed": 0}

    def _minutes(self) -> int:
        value = self.document.get_value("minutes")
        return min(120, max(1, int(value))) if value.isdigit() else 25


def build(app: Application, stats_file: Path) -> FocusTimer:
    window = app.open_html(PAGE, title="Focus timer", width=420, height=360)
    timer = FocusTimer(app, window, stats_file)
    timer.document.set_text("sessions", f"Completed sessions: {timer.stats['completed']}")
    return timer


def setup(app: Application) -> None:
    """Entry point for ``python -m nativehtmlkit run focus_timer:setup``; the runner calls app.run()."""
    stats = Path(app.rpc.call("desktop.paths")["state"]) / "focus-timer.json"
    build(app, stats)


def main() -> None:
    with Application.start(name="Focus timer", app_id=APP_ID) as app:
        setup(app)
        app.run()


if __name__ == "__main__":
    main()
