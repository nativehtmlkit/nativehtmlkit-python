"""Async job runner: start, watch and cancel concurrent asyncio tasks from the UI.

What it teaches
  * ``app.async_adapter()``: async event callbacks that run on YOUR asyncio loop
  * awaitable document updates with ``adapter.rpc.call("document.command", ...)``
  * one asyncio task per job, progress updates, cancellation with ``task.cancel()``
  * ``asyncio.to_thread`` for synchronous SDK calls (never block the loop)
  * ``await adapter.run()`` waits for shutdown; remaining tasks are cancelled afterwards

Run:  python examples/async_jobs.py      (or: python -m nativehtmlkit run async_jobs:amain)
"""
from __future__ import annotations

import asyncio
import random

from nativehtmlkit import Application, NativeHTMLKitError

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { margin:0; padding:18px 22px; font:14px sans-serif; background:#f3f5f9; color:#1f2430; }
  h1 { font-size:20px; margin:0 0 12px; }
  form { display:flex; gap:8px; margin-bottom:14px; }
  input { width:80px; padding:6px; }
  button { padding:6px 12px; border:1px solid #a9b2c3; border-radius:5px; background:#fff; cursor:pointer; }
  .job { background:#fff; border-radius:8px; padding:10px 12px; margin-bottom:8px; display:flex; gap:12px; align-items:center; }
  .job .name { width:70px; font-weight:bold; }
  .track { flex:1; height:8px; background:#e2e6ee; border-radius:4px; }
  .fill { height:8px; width:0%; background:#3b74e8; border-radius:4px; }
  .job.done .fill { background:#2f9e5b; } .job.cancelled .fill { background:#c4573a; }
  .state { width:90px; color:#5d6678; }
</style></head>
<body>
  <h1>Background jobs</h1>
  <form id="new-job"><label>Duration (s) <input id="seconds" type="number" min="1" max="30" value="4"></label>
    <button id="start" type="submit">Start job</button></form>
  <div id="jobs"></div>
  <p id="summary">No jobs yet.</p>
</body></html>"""


class JobRunner:
    def __init__(self, app: Application, window):
        self.app, self.window, self.document = app, window, window.document
        self.adapter = app.async_adapter()   # must be created inside the running loop
        self.tasks: dict[int, asyncio.Task] = {}
        self.states: dict[int, str] = {}
        self.next_id = 1
        self.adapter.on_document_event(self.document, "submit", self.on_submit, element="new-job")
        self.adapter.on_document_event(self.document, "click", self.on_click, element="jobs")

    async def command(self, op: str, **fields):
        """Awaitable Document.command(): the loop keeps running while the host answers."""
        return await self.adapter.rpc.call("document.command", {
            "window_id": self.window.id, "document_id": self.document.id,
            "command": {"op": op, **fields}})

    async def on_submit(self, _event: dict) -> None:
        seconds = (await self.command("get_value", element="seconds"))["value"]
        self.start_job(float(seconds) if seconds.replace(".", "", 1).isdigit() else 4.0)

    async def on_click(self, event: dict) -> None:
        parts = event["element"].split("-")          # "job-3-cancel"
        if len(parts) == 3 and parts[2] == "cancel" and parts[1].isdigit():
            task = self.tasks.get(int(parts[1]))
            if task and not task.done():
                task.cancel()

    def start_job(self, seconds: float) -> int:
        job_id, self.next_id = self.next_id, self.next_id + 1
        self.states[job_id] = "queued"
        self.tasks[job_id] = asyncio.create_task(self.run_job(job_id, seconds), name=f"job-{job_id}")
        return job_id

    async def run_job(self, job_id: int, seconds: float) -> None:
        await self.command("insert_html", element="jobs", position="beforeend", html=(
            f'<div class="job" id="job-{job_id}"><span class="name">Job {job_id}</span>'
            f'<div class="track"><div class="fill" id="job-{job_id}-fill"></div></div>'
            f'<span class="state" id="job-{job_id}-state">running</span>'
            f'<button id="job-{job_id}-cancel">Cancel</button></div>'))
        self.states[job_id] = "running"
        await self.summary()
        steps = 20
        try:
            for step in range(1, steps + 1):
                await asyncio.sleep(seconds / steps * random.uniform(0.6, 1.4))   # simulated work
                await self.command("set_attribute", element=f"job-{job_id}-fill", name="style",
                                   value=f"width:{step * 100 // steps}%")
            outcome = "done"
        except asyncio.CancelledError:
            outcome = "cancelled"
        self.states[job_id] = outcome
        try:
            await self.command("batch", ops=[
                {"op": "add_class", "element": f"job-{job_id}", "name": outcome},
                {"op": "set_text", "element": f"job-{job_id}-state", "text": outcome},
                {"op": "remove_element", "element": f"job-{job_id}-cancel"}])
            await self.summary()
        except NativeHTMLKitError:
            pass                                   # the window is gone (application quitting)

    async def summary(self) -> None:
        counts = {s: list(self.states.values()).count(s) for s in ("running", "done", "cancelled")}
        await self.command("set_text", element="summary", text=", ".join(f"{n} {s}" for s, n in counts.items()))


async def amain(app: Application) -> None:
    window = await asyncio.to_thread(app.open_html, PAGE, title="Background jobs", width=620, height=480)
    runner = JobRunner(app, window)
    try:
        await runner.adapter.run()                 # until the window is closed / the app quits
    finally:
        for task in runner.tasks.values():
            task.cancel()


def main() -> None:
    with Application.start(name="Background jobs") as app:
        asyncio.run(amain(app))


if __name__ == "__main__":
    main()
