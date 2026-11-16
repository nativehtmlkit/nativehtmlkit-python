"""Tutorial step 3: complete and delete items with one delegated handler.

Run:  uv run tutorial/step3_complete_delete.py
"""
import html

from nativehtmlkit import Application

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


def main() -> None:
    with Application.start(name="Todo") as app:
        window = app.open_html(PAGE, title="Todo", width=640, height=480)
        doc = window.document
        todos: list[dict] = []
        next_id = 1

        def row(todo: dict) -> str:
            n = todo["id"]
            return (f'<li id="todo-{n}" class="{"done" if todo["done"] else ""}">'
                    f'<input id="todo-{n}-done" type="checkbox"{" checked" if todo["done"] else ""}>'
                    f'<span class="text">{html.escape(todo["title"])}</span>'
                    f'<button id="todo-{n}-delete" class="plain">Delete</button></li>')

        def render() -> None:
            doc.replace_html("todos", "".join(row(t) for t in todos))
            left = sum(not t["done"] for t in todos)
            doc.set_text("count", f"{left} items left")

        def parse(element: str):
            # Element IDs carry the item number and the action: "todo-7-delete".
            parts = element.split("-")
            return (int(parts[1]), parts[2]) if len(parts) == 3 and parts[1].isdigit() else (None, None)

        def on_submit(_event: dict) -> None:
            nonlocal next_id
            title = doc.get_value("new-title").strip()
            if title:
                todos.append({"id": next_id, "title": title, "done": False})
                next_id += 1
                doc.set_value("new-title", "")
                render()

        def on_change(event: dict) -> None:
            todo_id, action = parse(event["element"])
            if action == "done":
                next(t for t in todos if t["id"] == todo_id)["done"] = bool(event.get("checked"))
                render()

        def on_click(event: dict) -> None:
            todo_id, action = parse(event["element"])
            if action == "delete":
                todos[:] = [t for t in todos if t["id"] != todo_id]
                render()

        doc.on("submit", on_submit, element="new-form")
        # element="todos" also matches events whose target is INSIDE the list: the event's
        # "path" lists every identified ancestor, and "element" is the nearest one.
        doc.on("change", on_change, element="todos")
        doc.on("click", on_click, element="todos")
        app.run()


if __name__ == "__main__":
    main()
