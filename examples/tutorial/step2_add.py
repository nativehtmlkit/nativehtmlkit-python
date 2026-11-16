"""Tutorial step 2: add items with a form and keep user text safe.

Run:  python examples/tutorial/step2_add.py
"""
import html

from nativehtmlkit import Application

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { margin:0; background:#f6f7fb; color:#1d2433; font:15px/1.4 sans-serif; }
  main { max-width:560px; margin:32px auto; padding:0 20px; }
  form { display:flex; gap:8px; }
  input { flex:1; padding:9px 10px; border:1px solid #e3e6ee; border-radius:6px; }
  button { padding:8px 12px; border:0; border-radius:6px; background:#3a6ff7; color:#fff; }
  ul { list-style:none; padding:0; background:#fff; border-radius:8px; }
  li { padding:10px 12px; border-bottom:1px solid #e3e6ee; }
</style></head>
<body><main>
  <h1>Todo</h1>
  <form id="new-form">
    <input id="new-title" type="text" placeholder="What needs doing?" required>
    <button id="add" type="submit">Add</button>
  </form>
  <ul id="todos"></ul>
  <p id="count">0 items</p>
</main></body></html>"""


def main() -> None:
    with Application.start(name="Todo") as app:
        window = app.open_html(PAGE, title="Todo", width=640, height=480)
        doc = window.document
        titles: list[str] = []

        def render() -> None:
            # html.escape: a title such as "<b>" is shown as text, never parsed as markup.
            doc.replace_html("todos", "".join(f"<li>{html.escape(t)}</li>" for t in titles))
            doc.set_text("count", f"{len(titles)} items")  # set_text never parses markup

        def on_submit(_event: dict) -> None:
            title = doc.get_value("new-title").strip()
            if title:
                titles.append(title)
                doc.set_value("new-title", "")
                render()

        # Clicking Add, or pressing Enter in the field, submits the form.
        doc.on("submit", on_submit, element="new-form")
        app.run()


if __name__ == "__main__":
    main()
