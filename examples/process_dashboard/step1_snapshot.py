"""Process dashboard tutorial, step 1: show a table of the busiest processes in a native window.

What it teaches
  * ``Application.start`` -> ``open_html`` -> ``replace_html`` -> ``app.run()``
  * building HTML rows from data with ``html.escape``
  * filling the page before ``app.run()`` announces readiness, so the window opens complete

Run:    uv run process_dashboard/step1_snapshot.py
Guide:  docs/tutorials/process-dashboard.md (step 1 of 3)
"""
from __future__ import annotations

import html

from nativehtmlkit import Application
from processes import list_processes

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { font: 14px sans-serif; margin: 0; background: #11161f; color: #e6ebf3; }
  main { padding: 18px 22px; }
  h1 { font-size: 20px; margin: 0 0 12px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #2a3445; }
  th { color: #9fb0c8; font-weight: 600; }
  td.num, th.num { text-align: right; }
</style></head>
<body><main>
  <h1>Top processes by memory</h1>
  <table>
    <thead><tr><th>Name</th><th class="num">Id</th><th class="num">Memory (MB)</th><th class="num">CPU (s)</th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
</main></body></html>"""


def rows_html(processes) -> str:
    # Process names are not under your control: escape them before they become markup.
    return "".join(f'<tr><td>{html.escape(p.name)}</td><td class="num">{p.pid}</td>'
                   f'<td class="num">{p.memory_mb:,.1f}</td><td class="num">{p.cpu_seconds:,.1f}</td></tr>'
                   for p in processes)


def build(app: Application):
    window = app.open_html(PAGE, title="Process Dashboard", width=720, height=560)
    top = sorted(list_processes(), key=lambda p: p.memory_mb, reverse=True)[:15]
    window.document.replace_html("rows", rows_html(top))
    return window.document


def main() -> None:
    # The host runs this script again as its backend: keep side effects inside main().
    with Application.start(name="Process Dashboard") as app:
        build(app)
        app.run()


if __name__ == "__main__":
    main()
