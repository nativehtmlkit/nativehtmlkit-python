"""Tutorial step 1: open a native window with HTML and CSS.

Run:  python examples/tutorial/step1_window.py
See docs/tutorials/todo-app.md for the explanation.
"""
from nativehtmlkit import Application

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { margin:0; background:#f6f7fb; color:#1d2433; font:15px/1.4 sans-serif; }
  main { max-width:560px; margin:32px auto; padding:0 20px; }
  h1 { font-size:28px; margin:0 0 16px; }
  ul { list-style:none; padding:0; background:#fff; border-radius:8px; }
  li { padding:10px 12px; border-bottom:1px solid #e3e6ee; }
</style></head>
<body><main>
  <h1>Todo</h1>
  <ul id="todos"><li>Learn NativeHTMLKit</li><li>Build an app</li></ul>
</main></body></html>"""


def main() -> None:
    # Everything with side effects lives inside main(): Application.start() runs this
    # script a second time as the host-supervised backend.
    with Application.start(name="Todo") as app:
        app.open_html(PAGE, title="Todo", width=640, height=480)
        app.run()  # returns when the user closes the window


if __name__ == "__main__":
    main()
