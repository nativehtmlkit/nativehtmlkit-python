"""Async counter: async callbacks on the owning event loop, awaitable RPC, clean shutdown.

What it teaches (Python-specific: asyncio basics)
  * ``app.async_adapter()``: the same host connection, with callbacks that run on YOUR loop
  * ``async def`` event handlers registered with ``adapter.on_document_event``
  * awaitable RPC (``await adapter.rpc.call(...)``) that keeps the loop responsive
  * ``await adapter.run()``, which returns when the window is closed or the app quits

Run:  uv run async_counter.py   (or: uv run -m nativehtmlkit run async_counter:amain)
"""
from __future__ import annotations

import asyncio

from nativehtmlkit import Application, Window

HTML = """<main style="padding:20px;font-family:sans-serif">
<h1>Async counter</h1>
<button id="inc">Add one</button> <span id="count">0</span>
<p id="status">Ready</p></main>"""


class AsyncCounter:
    def __init__(self, app: Application, window: Window):
        self.window, self.document = window, window.document
        self.adapter = app.async_adapter()   # callbacks registered here run on the current loop
        self.count = 0
        self.adapter.on_document_event(self.document, "click", self.increment, element="inc")

    async def increment(self, _event: dict) -> None:
        self.count += 1
        # Awaitable RPC: the loop keeps running while the host answers.
        await self.adapter.rpc.call("document.command", {
            "window_id": self.window.id, "document_id": self.document.id,
            "command": {"op": "set_text", "element": "count", "text": str(self.count)}})


async def amain(app: Application) -> None:
    # Blocking SDK calls go through a thread so they never stall the loop.
    window = await asyncio.to_thread(app.open_html, HTML, title="NativeHTMLKit async counter", width=420, height=260)
    counter = AsyncCounter(app, window)
    await counter.adapter.run()   # returns after the window is closed / the app quits


def main() -> None:
    with Application.start(name="Async counter") as app:
        asyncio.run(amain(app))


if __name__ == "__main__":
    main()
