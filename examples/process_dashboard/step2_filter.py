"""Process dashboard tutorial, step 2: filter and sort the table.

What it teaches
  * ``input``, ``change`` and ``submit`` events that all call one ``update_view`` function
  * reading controls with ``get_value``
  * ``set_text`` for text that must never be parsed as HTML

Run:    uv run process_dashboard/step2_filter.py
Guide:  docs/tutorials/process-dashboard.md (step 2 of 3)
"""
from __future__ import annotations

import html

from nativehtmlkit import Application, Document
from processes import list_processes

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { font: 14px sans-serif; margin: 0; background: #11161f; color: #e6ebf3; }
  main { padding: 18px 22px; }
  h1 { font-size: 20px; margin: 0 0 12px; }
  form { display: flex; gap: 8px; margin-bottom: 10px; }
  input, select { background: #1b2331; color: #e6ebf3; border: 1px solid #3a475c; border-radius: 5px; padding: 6px; }
  #filter { flex: 1; }
  button { background: #3574c6; color: white; border: 0; border-radius: 5px; padding: 6px 12px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #2a3445; }
  th { color: #9fb0c8; font-weight: 600; }
  td.num, th.num { text-align: right; }
  #summary { color: #9fb0c8; }
</style></head>
<body><main>
  <h1>Processes</h1>
  <form id="view-form">
    <input id="filter" type="search" placeholder="Filter by name" aria-label="Filter by name">
    <select id="sort" aria-label="Sort by">
      <option value="memory">Memory</option><option value="cpu">CPU time</option><option value="name">Name</option>
    </select>
    <button id="apply">Refresh</button>
  </form>
  <p id="summary"></p>
  <table>
    <thead><tr><th>Name</th><th class="num">Id</th><th class="num">Memory (MB)</th><th class="num">CPU (s)</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
</main></body></html>"""

SORT_KEYS = {
    "memory": (lambda p: p.memory_mb, True),
    "cpu": (lambda p: p.cpu_seconds, True),
    "name": (lambda p: p.name.lower(), False),
}
SHOWN = 25


def update_view(document: Document) -> None:
    needle = document.get_value("filter").strip().lower()
    key, descending = SORT_KEYS.get(document.get_value("sort"), SORT_KEYS["memory"])
    everything = list_processes()
    shown = [p for p in everything if needle in p.name.lower()]
    top = sorted(shown, key=key, reverse=descending)[:SHOWN]
    document.replace_html("rows", "".join(
        f'<tr><td>{html.escape(p.name)}</td><td class="num">{p.pid}</td>'
        f'<td class="num">{p.memory_mb:,.1f}</td><td class="num">{p.cpu_seconds:,.1f}</td></tr>' for p in top))
    document.set_text("summary", f"Showing {len(top)} of {len(everything)} processes")


def build(app: Application) -> Document:
    window = app.open_html(PAGE, title="Process Dashboard", width=720, height=600)
    document = window.document
    # Callbacks run later, on the SDK's event thread, and may call any SDK method.
    document.on("input", lambda _event: update_view(document), element="filter")
    document.on("change", lambda _event: update_view(document), element="sort")
    document.on("submit", lambda _event: update_view(document), element="view-form")
    update_view(document)
    return document


def main() -> None:
    with Application.start(name="Process Dashboard") as app:
        build(app)
        app.run()


if __name__ == "__main__":
    main()
