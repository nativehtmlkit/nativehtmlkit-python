"""Tutorial step 4: edit in place, keyboard handling and a small controller class.

Run:  uv run tutorial/step4_edit_keyboard.py
Step 5 (persistence and styling) is examples/todo.py.
"""
from __future__ import annotations

import html

from nativehtmlkit import Application, Window

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { margin:0; background:#f6f7fb; color:#1d2433; font:15px/1.4 sans-serif; }
  main { max-width:560px; margin:32px auto; padding:0 20px; }
  form { display:flex; gap:8px; }
  input[type=text] { flex:1; padding:9px 10px; border:1px solid #e3e6ee; border-radius:6px; }
  button { padding:8px 12px; border:0; border-radius:6px; background:#3a6ff7; color:#fff; }
  button.plain { background:transparent; color:#6b7385; }
  ul { list-style:none; padding:0; background:#fff; border-radius:8px; }
  li { display:flex; align-items:center; gap:10px; padding:10px 12px; border-bottom:1px solid #e3e6ee; }
  li .text { flex:1; }
  li form { flex:1; }
  li.done .text { text-decoration:line-through; color:#6b7385; }
</style></head>
<body><main>
  <h1>Todo</h1>
  <form id="new-form">
    <input id="new-title" type="text" placeholder="What needs doing?" required>
    <button id="add" type="submit">Add</button>
  </form>
  <ul id="todos"></ul>
  <p id="count">0 items left</p>
</main></body></html>"""


class TodoApp:
    def __init__(self, window: Window):
        self.doc = window.document
        self.todos: list[dict] = []
        self.next_id = 1
        self.editing: int | None = None
        self.doc.on("submit", self.on_submit)          # both the new-item and the edit form
        self.doc.on("change", self.on_change, element="todos")
        self.doc.on("click", self.on_click, element="todos")
        self.doc.on("keydown", self.on_key, element="todos")
        self.render()

    def row(self, todo: dict) -> str:
        n, title = todo["id"], html.escape(todo["title"])
        if n == self.editing:
            # Enter in this field submits its form; Escape is handled in on_key.
            return (f'<li id="todo-{n}"><form id="edit-form-{n}">'
                    f'<input id="edit-title" type="text" value="{title}"></form></li>')
        return (f'<li id="todo-{n}" class="{"done" if todo["done"] else ""}">'
                f'<input id="todo-{n}-done" type="checkbox"{" checked" if todo["done"] else ""}>'
                f'<span class="text">{title}</span>'
                f'<button id="todo-{n}-edit" class="plain">Edit</button>'
                f'<button id="todo-{n}-delete" class="plain">Delete</button></li>')

    def render(self) -> None:
        self.doc.replace_html("todos", "".join(self.row(t) for t in self.todos))
        self.doc.set_text("count", f"{sum(not t['done'] for t in self.todos)} items left")

    def find(self, todo_id: int) -> dict:
        return next(t for t in self.todos if t["id"] == todo_id)

    def on_submit(self, event: dict) -> None:
        if event["element"] == "new-form":
            title = self.doc.get_value("new-title").strip()
            if title:
                self.todos.append({"id": self.next_id, "title": title, "done": False})
                self.next_id += 1
                self.doc.set_value("new-title", "")
        elif event["element"].startswith("edit-form-"):
            title = self.doc.get_value("edit-title").strip()
            if title:
                self.find(self.editing)["title"] = title
            self.editing = None
        self.render()

    def on_change(self, event: dict) -> None:
        todo_id, action = parse(event["element"])
        if action == "done":
            self.find(todo_id)["done"] = bool(event.get("checked"))
            self.render()

    def on_click(self, event: dict) -> None:
        todo_id, action = parse(event["element"])
        if action == "delete":
            self.todos = [t for t in self.todos if t["id"] != todo_id]
            self.render()
        elif action == "edit":
            self.editing = todo_id
            self.render()
            self.doc.focus("edit-title")

    def on_key(self, event: dict) -> None:
        # keydown events carry "key" (for example "Enter", "Escape", "a") and modifier flags.
        if event.get("key") == "Escape" and self.editing is not None:
            self.editing = None
            self.render()


def parse(element: str):
    parts = element.split("-")
    return (int(parts[1]), parts[2]) if len(parts) == 3 and parts[1].isdigit() else (None, None)


def main() -> None:
    with Application.start(name="Todo") as app:
        TodoApp(app.open_html(PAGE, title="Todo", width=640, height=480))
        app.run()


if __name__ == "__main__":
    main()
