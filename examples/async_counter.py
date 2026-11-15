"""Asyncio example: async callbacks on the owning loop, awaitable RPC, clean shutdown.

Run:  python examples/async_counter.py   (or: python -m nativehtmlkit run async_counter:main)
"""
import asyncio

from nativehtmlkit import Application

HTML = """<main style="padding:20px;font-family:sans-serif">
<h1>Async counter</h1>
<button id="inc">Add one</button> <span id="count">0</span>
<p id="status">Ready</p></main>"""


async def amain(app: Application) -> None:
    window = await asyncio.to_thread(app.open_html, HTML, title="NativeHTMLKit async counter", width=420, height=260)
    document = window.document
    adapter = app.async_adapter()  # same connection; callbacks run on this loop
    count = 0

    async def increment(_event):
        nonlocal count
        count += 1
        # Awaitable RPC: the loop keeps running while the host answers.
        await adapter.rpc.call("document.command", {"window_id": window.id, "document_id": document.id,
                                                    "command": {"op": "set_text", "element": "count", "text": str(count)}})

    adapter.on_document_event(document, "click", increment, element="inc")
    await adapter.run()  # returns after the window is closed / the app quits


def main() -> None:
    with Application.start(name="Async counter") as app:
        asyncio.run(amain(app))


if __name__ == "__main__":
    main()
