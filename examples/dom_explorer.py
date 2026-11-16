"""DOM explorer: browse the live element tree and edit nodes that have no HTML id.

What it teaches
  * ``Document.node()`` / ``query_nodes()``: opaque node references, also for elements without an id
  * ``Node.inspect()`` and ``Node.children()`` (paginated) to walk the tree
  * ``Node`` mutations: ``add_class``, ``set_text``, ``move_to`` and ``remove``
  * node references belong to ONE document generation: after a reload they are stale

Run:  python examples/dom_explorer.py
Click a node in the tree on the left; the matching element in the sample is highlighted.
"""
from __future__ import annotations

import html

from nativehtmlkit import Application, NativeHTMLKitError, Node, Window

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { margin:0; font:13px sans-serif; display:flex; height:100vh; color:#1d2230; }
  #tree { width:320px; overflow:auto; background:#f3f4f8; border-right:1px solid #d9dde6; padding:8px 0; font-family:monospace; }
  .item { padding:2px 8px; cursor:pointer; white-space:nowrap; }
  .item:hover { background:#e1e8fa; } .item.current { background:#c9d8fb; }
  .tag { color:#7c3aa8; } .attr { color:#9a6a00; } .text { color:#4a7a2a; }
  .right { flex:1; display:flex; flex-direction:column; }
  .tools { padding:8px 12px; display:flex; gap:6px; border-bottom:1px solid #d9dde6; align-items:center; }
  #info { color:#5c6577; margin-left:8px; font-family:monospace; }
  #sample { padding:16px 20px; overflow:auto; }
  .highlight { outline:2px solid #e8590c; background:#fff4e6; }
</style></head>
<body>
  <div id="tree"></div>
  <div class="right">
    <div class="tools"><button id="up">Move up</button><button id="shout">UPPERCASE text</button>
      <button id="delete">Delete</button><button id="reset">Reset sample</button><span id="info">Nothing selected</span></div>
    <div id="sample"></div>
  </div>
</body></html>"""

SAMPLE = """<article><h2>Release notes</h2>
<p>Elements in this sample have <em>no</em> id attributes.</p>
<ul><li>Faster layout</li><li>Smaller binaries</li><li>Better <code>dialog</code> support</li></ul>
<blockquote>Node references work without ids.</blockquote></article>"""


class Explorer:
    def __init__(self, window: Window):
        self.document = doc = window.document
        self.items: list[Node] = []          # tree row index -> node reference
        self.current: Node | None = None
        doc.on("click", self._on_tree_click, element="tree")
        doc.on("click", lambda _e: self.move_up(), element="up")
        doc.on("click", lambda _e: self.uppercase(), element="shout")
        doc.on("click", lambda _e: self.delete(), element="delete")
        doc.on("click", lambda _e: self.reset(), element="reset")
        self.reset()

    def reset(self) -> None:
        self.document.replace_html("sample", SAMPLE)
        self.current = None
        self.document.set_text("info", "Nothing selected")
        self.refresh()

    def refresh(self) -> None:
        """Walk the sample subtree with Node.children() and render one row per node."""
        self.items, rows = [], []

        def walk(node: Node, depth: int) -> None:
            listing = node.children(limit=256)
            for child in listing["children"]:
                ref = self.document.node(reference=child["node"])
                info = ref.inspect()
                if info["type"] == "text":
                    text = info.get("text", "").strip()      # text nodes report their text
                    if not text:
                        continue                              # skip whitespace between tags
                    label = f'<span class="text">"{html.escape(text[:40])}"</span>'
                elif info["type"] == "element":
                    attrs = "".join(f' <span class="attr">{html.escape(k)}="{html.escape(v)}"</span>'
                                    for k, v in info.get("attributes", {}).items())
                    label = f'<span class="tag">&lt;{html.escape(info["name"])}&gt;</span>{attrs}'
                else:
                    continue
                current = " current" if self.current and self.current.id == ref.id else ""
                rows.append(f'<div id="item-{len(self.items)}" class="item{current}" '
                            f'style="padding-left:{8 + depth * 14}px">{label}</div>')
                self.items.append(ref)
                if info["type"] == "element":
                    walk(ref, depth + 1)

        walk(self.document.node("sample"), 0)
        self.document.replace_html("tree", "".join(rows))

    def select(self, index: int) -> None:
        if self.current is not None:
            try:
                self.current.remove_class("highlight")
            except NativeHTMLKitError:
                pass                          # the previous node may have been deleted
        self.current = self.items[index]
        info = self.current.inspect()
        if info["type"] == "element":
            self.current.add_class("highlight")
        self.document.set_text("info", f"{info.get('name') or info['type']} · {info['node']}")
        self.refresh()

    def move_up(self) -> None:
        if self.current is None:
            return
        previous = self.current.inspect().get("previous")
        # Skip whitespace text nodes; move before the previous ELEMENT sibling.
        while previous and self.document.node(reference=previous).inspect()["type"] != "element":
            previous = self.document.node(reference=previous).inspect().get("previous")
        if previous:
            self.current.move_to(self.document.node(reference=previous), position="beforebegin")
            self.refresh()

    def uppercase(self) -> None:
        """Uppercase an element whose only child is text (set_text replaces ALL children)."""
        if self.current is None or self.current.inspect()["type"] != "element":
            return
        children = self.current.children()["children"]
        if len(children) == 1 and children[0]["type"] == "text":
            text = self.document.node(reference=children[0]["node"]).inspect()["text"]
            self.current.set_text(text.upper())
            self.refresh()

    def delete(self) -> None:
        if self.current is not None:
            self.current.remove()
            self.current = None
            self.document.set_text("info", "Deleted")
            self.refresh()

    def _on_tree_click(self, event: dict) -> None:
        element = event["element"]
        if element.startswith("item-") and element[5:].isdigit():
            self.select(int(element[5:]))


def build(app: Application) -> Explorer:
    return Explorer(app.open_html(PAGE, title="DOM explorer", width=900, height=560))


def main() -> None:
    with Application.start(name="DOM explorer") as app:
        build(app)
        app.run()


if __name__ == "__main__":
    main()
