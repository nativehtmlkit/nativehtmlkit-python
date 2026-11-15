"""Shared by the integration test driver (pytest) and the backend apps it launches.

The backend app runs inside the real Core host's supervised process; it reports
behaviour assertions as JSON lines to ``$NHK_IT_OUT`` so the driver can assert on
them after the host exits. Nothing here talks to the host itself.
"""
from __future__ import annotations

import json
import os
import threading
import time
import traceback

_lock = threading.Lock()


def emit(kind: str, **fields) -> None:
    path = os.environ.get("NHK_IT_OUT")
    if not path:
        return
    line = json.dumps({"kind": kind, "t": round(time.time(), 3), **fields}, ensure_ascii=False, default=repr)
    with _lock, open(path, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def check(name: str, condition, **detail) -> bool:
    emit("check", name=name, status="pass" if condition else "fail", **detail)
    return bool(condition)


def expect_raises(name: str, kinds, function, *args, **kwargs):
    try:
        function(*args, **kwargs)
    except kinds as error:
        check(name, True, error=type(error).__name__, code=getattr(error, "code", None))
        return error
    except Exception as error:  # wrong type is a failure, with evidence
        check(name, False, error=type(error).__name__, message=str(error)[:200])
        return error
    check(name, False, error="no exception raised")
    return None


class Guard:
    """Record an unexpected exception in a scenario as a failed check, then continue."""

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, kind, error, tb):
        if error is not None and not isinstance(error, (SystemExit, KeyboardInterrupt)):
            emit("check", name=self.name, status="fail", error=type(error).__name__,
                 message=str(error)[:300], trace="".join(traceback.format_tb(tb))[-1500:])
            return True
        return False


def quit_when_ready(app, *, delay: float = 0.0, then=None) -> threading.Thread:
    """After ``app.run()`` announced readiness, optionally run ``then()`` and request quit."""
    def worker():
        deadline = time.monotonic() + 30
        while not app._ready and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(delay)
        try:
            if then is not None:
                then()
        except Exception as error:
            check("quit_when_ready.then", False, error=type(error).__name__, message=str(error)[:200])
        try:
            app.request_quit()
        except Exception as error:  # already shutting down is fine; record the type
            emit("note", name="request_quit_failed", error=type(error).__name__)
    thread = threading.Thread(target=worker, name="it-quit", daemon=True)
    thread.start()
    return thread
