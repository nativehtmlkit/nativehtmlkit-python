"""Data table: search, sort, page through and inspect a list of records.

What it teaches
  * re-rendering a region with ``replace_html`` built from escaped data
  * live search with the ``input`` event (the event carries the control's current ``value``)
  * a ``<select>`` ``change`` event, sortable column headers and pagination buttons
  * a details pane updated with ``set_text`` (always plain text)
  * splitting state (Python) from presentation (HTML/CSS)

Run:  uv run data_table.py
"""
from __future__ import annotations

import html
import random

from nativehtmlkit import Application, Window

COLUMNS = [("sku", "SKU"), ("name", "Product"), ("category", "Category"), ("stock", "Stock"), ("price", "Price")]


def sample_inventory(count: int = 240, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)          # deterministic: the same rows on every start
    adjectives = ["Compact", "Deluxe", "Eco", "Heavy-duty", "Mini", "Smart", "Travel", "Ultra"]
    things = {"Kitchen": ["kettle", "blender", "toaster"], "Office": ["stapler", "lamp", "chair"],
              "Garden": ["hose", "rake", "planter"], "Audio": ["speaker", "headset", "radio"]}
    rows = []
    for n in range(1, count + 1):
        category = rng.choice(sorted(things))
        rows.append({"sku": f"SKU-{n:04d}", "name": f"{rng.choice(adjectives)} {rng.choice(things[category])}",
                     "category": category, "stock": rng.randint(0, 500), "price": round(rng.uniform(3, 400), 2)})
    return rows


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { margin:0; font:13px sans-serif; background:#f4f5f8; color:#1e2330; display:flex; height:100vh; }
  .main { flex:1; display:flex; flex-direction:column; padding:14px 16px; min-width:0; }
  .tools { display:flex; gap:10px; align-items:center; margin-bottom:10px; }
  input[type=search] { flex:1; padding:7px; border:1px solid #c3c9d6; border-radius:5px; }
  .scroll { flex:1; overflow:auto; background:#fff; border-radius:6px; }
  table { width:100%; border-collapse:collapse; }
  th { position:sticky; top:0; background:#e9ecf2; text-align:left; padding:7px 8px; cursor:pointer; }
  th.sorted-asc::after { content:" ▲"; } th.sorted-desc::after { content:" ▼"; }
  td { padding:6px 8px; border-bottom:1px solid #eceef3; }
  td.num { text-align:right; font-variant-numeric:tabular-nums; }
  tr.low td { color:#b03a2e; }
  tr.selected td { background:#dce7fd; }
  .pager { display:flex; gap:8px; align-items:center; margin-top:8px; }
  button { padding:4px 10px; }
  aside { width:240px; padding:16px; background:#fff; border-left:1px solid #dde1e8; }
  aside dt { color:#6a7284; margin-top:8px; } aside dd { margin:2px 0 0; font-weight:bold; }
</style></head>
<body>
  <div class="main">
    <div class="tools">
      <input id="search" type="search" placeholder="Search name, SKU or category">
      <label>Category <select id="category"><option value="">All</option>
        <option>Audio</option><option>Garden</option><option>Kitchen</option><option>Office</option></select></label>
    </div>
    <div class="scroll"><table>
      <thead><tr id="headers">%HEADERS%</tr></thead><tbody id="rows"></tbody></table></div>
    <div class="pager"><button id="prev">‹ Previous</button><span id="page">-</span>
      <button id="next">Next ›</button><span id="matches"></span></div>
  </div>
  <aside><h2>Details</h2><dl>
    <dt>SKU</dt><dd id="d-sku">-</dd><dt>Product</dt><dd id="d-name">-</dd>
    <dt>Category</dt><dd id="d-category">-</dd><dt>Stock</dt><dd id="d-stock">-</dd><dt>Price</dt><dd id="d-price">-</dd>
  </dl></aside>
</body></html>""".replace("%HEADERS%", "".join(f'<th id="col-{key}">{label}</th>' for key, label in COLUMNS))


class DataTable:
    PAGE_SIZE = 25

    def __init__(self, window: Window, records: list[dict]):
        self.document = doc = window.document
        self.records = records
        self.query, self.category = "", ""
        self.sort_key, self.descending = "sku", False
        self.page = 0
        self.selected: str | None = None
        doc.on("input", lambda e: self.set_query(e.get("value", "")), element="search")
        doc.on("change", lambda e: self.set_category(e.get("value", "")), element="category")
        doc.on("click", self._on_header, element="headers")
        doc.on("click", lambda _e: self.go(-1), element="prev")
        doc.on("click", lambda _e: self.go(+1), element="next")
        doc.on("click", self._on_row, element="rows")
        self.render()

    def visible(self) -> list[dict]:
        needle = self.query.casefold()
        rows = [r for r in self.records
                if (not self.category or r["category"] == self.category)
                and (not needle or any(needle in str(r[k]).casefold() for k in ("sku", "name", "category")))]
        return sorted(rows, key=lambda r: r[self.sort_key], reverse=self.descending)

    def set_query(self, text: str) -> None:
        self.query, self.page = text.strip(), 0
        self.render()

    def set_category(self, category: str) -> None:
        self.category, self.page = category, 0
        self.render()

    def sort_by(self, key: str) -> None:
        self.descending = not self.descending if key == self.sort_key else False
        self.sort_key, self.page = key, 0
        self.render()

    def go(self, delta: int) -> None:
        self.page += delta
        self.render()

    def select(self, sku: str) -> None:
        record = next(r for r in self.records if r["sku"] == sku)
        self.selected = sku
        for key, _label in COLUMNS:
            self.document.set_text(f"d-{key}", str(record[key]))
        self.render()

    def render(self) -> None:
        rows = self.visible()
        pages = max(1, -(-len(rows) // self.PAGE_SIZE))
        self.page = max(0, min(self.page, pages - 1))
        start = self.page * self.PAGE_SIZE
        body = []
        for r in rows[start:start + self.PAGE_SIZE]:
            classes = " ".join(c for c, on in (("low", r["stock"] < 20), ("selected", r["sku"] == self.selected)) if on)
            sku = html.escape(r["sku"])
            body.append(f'<tr id="row-{sku}" class="{classes}"><td>{sku}</td><td>{html.escape(r["name"])}</td>'
                        f'<td>{html.escape(r["category"])}</td><td class="num">{r["stock"]}</td>'
                        f'<td class="num">{r["price"]:.2f}</td></tr>')
        # One batch = one round trip and one atomic document update (all or nothing).
        ops = [{"op": "replace_children_html", "element": "rows",
                "html": "".join(body) or '<tr><td colspan="5">No matching records.</td></tr>'}]
        for key, _label in COLUMNS:
            ops += [{"op": "remove_class", "element": f"col-{key}", "name": "sorted-asc"},
                    {"op": "remove_class", "element": f"col-{key}", "name": "sorted-desc"}]
        ops += [{"op": "add_class", "element": f"col-{self.sort_key}",
                 "name": "sorted-desc" if self.descending else "sorted-asc"},
                {"op": "set_text", "element": "page", "text": f"Page {self.page + 1} of {pages}"},
                {"op": "set_text", "element": "matches", "text": f"{len(rows)} of {len(self.records)} records"}]
        self.document.batch(ops)

    def _on_header(self, event: dict) -> None:
        if event["element"].startswith("col-"):
            self.sort_by(event["element"][4:])

    def _on_row(self, event: dict) -> None:
        # A click on a <td> (no id) reports the nearest identified ancestor: the row.
        if event["element"].startswith("row-"):
            self.select(event["element"][4:])


def build(app: Application, records: list[dict] | None = None) -> DataTable:
    window = app.open_html(PAGE, title="Inventory", width=980, height=640)
    return DataTable(window, sample_inventory() if records is None else records)


def main() -> None:
    with Application.start(name="Inventory") as app:
        build(app)
        app.run()


if __name__ == "__main__":
    main()
