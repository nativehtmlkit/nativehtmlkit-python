"""Todo list: add, edit, complete and delete tasks, saved to a JSON file.

What it teaches
  * form ``submit`` events (the Add button, or Enter in the text field, submits the form)
  * one delegated handler for a whole list (``element="todos"`` matches every child)
  * escaping user text with ``html.escape`` before ``replace_html``
  * keyboard handling (Escape cancels an edit) and in-place editing
  * persistence: an atomic JSON write into the per-application data directory

This is the finished app of the tutorial in docs/tutorials/todo-app.md.

Run:  uv run todo.py
Data: <per-user data directory>/todos.json (printed at start-up).
"""
from __future__ import annotations

import html
import json
import os
from pathlib import Path

from nativehtmlkit import Application, Window

APP_ID = "org.nativehtmlkit.examples.todo"

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  :root { --bg:#f6f7fb; --card:#fff; --text:#1d2433; --muted:#6b7385; --accent:#3a6ff7; --line:#e3e6ee; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#141923; --card:#1d2433; --text:#e8ecf5; --muted:#9aa3b5; --accent:#7aa2ff; --line:#2d3546; }
  }
  body { margin:0; background:var(--bg); color:var(--text); font:15px/1.4 sans-serif; }
  main { max-width:560px; margin:32px auto; padding:0 20px; }
  h1 { font-size:28px; margin:0 0 16px; }
  form { display:flex; gap:8px; }
  input[type=text] { flex:1; padding:9px 10px; border:1px solid var(--line); border-radius:6px;
                     background:var(--card); color:var(--text); }
  button { padding:8px 12px; border:0; border-radius:6px; background:var(--accent); color:#fff; cursor:pointer; }
  button.plain { background:transparent; color:var(--muted); padding:4px 8px; }
  ul { list-style:none; padding:0; margin:16px 0; background:var(--card); border-radius:8px; }
  li { display:flex; align-items:center; gap:10px; padding:10px 12px; border-bottom:1px solid var(--line); }
  li:last-child { border-bottom:0; }
  li .text { flex:1; }
  li.done .text { text-decoration:line-through; color:var(--muted); }
  li form { flex:1; }
  .empty { color:var(--muted); padding:16px 12px; }
  footer { display:flex; justify-content:space-between; align-items:center; color:var(--muted); }
  nav button { background:transparent; color:var(--muted); }
  nav button.active { color:var(--accent); font-weight:bold; }
</style></head>
<body><main>
  <h1>Todo</h1>
  <form id="new-form">
    <input id="new-title" type="text" placeholder="What needs doing?" required maxlength="200">
    <button id="add" type="submit">Add</button>
  </form>
  <ul id="todos"></ul>
  <footer>
    <span id="count">0 items left</span>
    <nav id="filters">
      <button id="filter-all" class="active">All</button>
      <button id="filter-active">Active</button>
      <button id="filter-done">Completed</button>
    </nav>
    <button id="clear-done" class="plain">Clear completed</button>
  </footer>
</main></body></html>"""

FILTERS = {"all": lambda item: True, "active": lambda item: not item["done"], "done": lambda item: item["done"]}


def load_todos(path: Path) -> list[dict]:
    """Read saved todos; a missing or unreadable file starts an empty list."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [{"id": int(x["id"]), "title": str(x["title"]), "done": bool(x["done"])}
            for x in data if isinstance(x, dict) and {"id", "title", "done"} <= x.keys()]


def save_todos(path: Path, todos: list[dict]) -> None:
    """Write atomically: a crash mid-write never leaves a truncated file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(todos, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


class TodoApp:
    def __init__(self, window: Window, store: Path):
        self.window, self.document, self.store = window, window.document, store
        self.todos = load_todos(store)
        self.next_id = max((t["id"] for t in self.todos), default=0) + 1
        self.filter = "all"
        self.editing: int | None = None
        doc = self.document
        doc.on("submit", self._on_submit)                    # new-form and the inline edit form
        doc.on("change", self._on_change, element="todos")   # checkboxes inside the list
        doc.on("click", self._on_list_click, element="todos")
        doc.on("keydown", self._on_key, element="todos")
        doc.on("click", self._on_filter_click, element="filters")
        doc.on("click", lambda _e: self.clear_done(), element="clear-done")
        self.render()

    # ----- actions (also called directly by the headless tests) -----
    def add(self, title: str) -> None:
        title = title.strip()
        if title:
            self.todos.append({"id": self.next_id, "title": title, "done": False})
            self.next_id += 1
            self.changed()

    def toggle(self, todo_id: int, done: bool) -> None:
        self._find(todo_id)["done"] = done
        self.changed()

    def rename(self, todo_id: int, title: str) -> None:
        self.editing = None
        if title.strip():
            self._find(todo_id)["title"] = title.strip()
        self.changed()

    def delete(self, todo_id: int) -> None:
        self.todos = [t for t in self.todos if t["id"] != todo_id]
        self.changed()

    def clear_done(self) -> None:
        self.todos = [t for t in self.todos if not t["done"]]
        self.changed()

    def set_filter(self, name: str) -> None:
        self.filter = name
        for key in FILTERS:
            (self.document.add_class if key == name else self.document.remove_class)(f"filter-{key}", "active")
        self.render()

    def start_edit(self, todo_id: int) -> None:
        self.editing = todo_id
        self.render()
        self.document.focus("edit-title")

    def changed(self) -> None:
        save_todos(self.store, self.todos)
        self.render()

    # ----- rendering -----
    def render(self) -> None:
        visible = [t for t in self.todos if FILTERS[self.filter](t)]
        rows = [self._row(t) for t in visible] or ['<li class="empty">Nothing here.</li>']
        left = sum(not t["done"] for t in self.todos)
        self.document.replace_html("todos", "".join(rows))
        self.document.set_text("count", f"{left} item{'s' if left != 1 else ''} left")

    def _row(self, todo: dict) -> str:
        n, title = todo["id"], html.escape(todo["title"])   # user text is never trusted markup
        if n == self.editing:
            return (f'<li id="todo-{n}"><form id="edit-form-{n}">'
                    f'<input id="edit-title" type="text" value="{title}" maxlength="200"></form>'
                    f'<button id="todo-{n}-cancel" class="plain">Cancel</button></li>')
        checked = " checked" if todo["done"] else ""
        return (f'<li id="todo-{n}" class="{"done" if todo["done"] else ""}">'
                f'<input id="todo-{n}-done" type="checkbox"{checked}>'
                f'<span id="todo-{n}-text" class="text">{title}</span>'
                f'<button id="todo-{n}-edit" class="plain">Edit</button>'
                f'<button id="todo-{n}-delete" class="plain">Delete</button></li>')

    # ----- event handlers -----
    def _on_submit(self, event: dict) -> None:
        if event["element"] == "new-form":
            self.add(self.document.get_value("new-title"))
            self.document.set_value("new-title", "")
        elif event["element"].startswith("edit-form-"):
            self.rename(int(event["element"].rsplit("-", 1)[1]), self.document.get_value("edit-title"))

    def _on_change(self, event: dict) -> None:
        todo_id, action = _parse(event["element"])
        if action == "done":
            self.toggle(todo_id, bool(event.get("checked")))

    def _on_list_click(self, event: dict) -> None:
        todo_id, action = _parse(event["element"])
        if action == "edit":
            self.start_edit(todo_id)
        elif action == "delete":
            self.delete(todo_id)
        elif action == "cancel":
            self.editing = None
            self.render()

    def _on_key(self, event: dict) -> None:
        if event.get("key") == "Escape" and self.editing is not None:
            self.editing = None
            self.render()

    def _on_filter_click(self, event: dict) -> None:
        name = event["element"].removeprefix("filter-")
        if name in FILTERS:
            self.set_filter(name)

    def _find(self, todo_id: int) -> dict:
        return next(t for t in self.todos if t["id"] == todo_id)


def _parse(element: str) -> tuple[int | None, str | None]:
    """'todo-7-delete' -> (7, 'delete'); anything else -> (None, None)."""
    parts = element.split("-")
    if len(parts) == 3 and parts[0] == "todo" and parts[1].isdigit():
        return int(parts[1]), parts[2]
    return None, None


def build(app: Application, store: Path) -> TodoApp:
    window = app.open_html(PAGE, title="Todo", width=640, height=620, min_width=420, min_height=360)
    return TodoApp(window, store)


def main() -> None:
    with Application.start(name="Todo", app_id=APP_ID) as app:
        # desktop.paths is a public Core v1 method: per-application config/data/cache directories.
        store = Path(app.rpc.call("desktop.paths")["data"]) / "todos.json"
        print("Saving todos to", store)
        build(app, store)
        app.run()


if __name__ == "__main__":
    main()
