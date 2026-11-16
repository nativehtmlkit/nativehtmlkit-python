# Examples and demos

- `examples/hello.py` — the smallest working event-driven Python application.
- `examples/async_counter.py` — asyncio integration with an async callback and awaited RPC.
- The public showcase repository contains `examples/python-sdk/gallery.py` — a guided native demo with counter, document operations, file picker, dialogs, multiple windows and bitmap surface.
- `python -m nativehtmlkit run module:main` — host-first runner to avoid duplicate top-level side effects.

The Python UI library is separate: it offers reactive controls via public SDK calls, whereas the SDK gives direct control of documents, windows and events. See the [public getting started guide](https://github.com/nativehtmlkit/nativehtmlkit/blob/main/docs/getting-started/python.md).
