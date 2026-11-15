"""FR-PY-01: backend output and the fatal traceback must reach the developer at every level."""
import os
import sys

from nativehtmlkit import Application


def main(app=None):
    if app is None:
        with Application.start(name="IT crash " + os.environ.get("NHK_IT_MARKER", ""), instance="multiple") as started:
            return main(started)
    print("STDOUT-LINE from backend", flush=True)
    print("STDERR-LINE from backend", file=sys.stderr, flush=True)
    app.open_html("<p>x</p>")
    raise RuntimeError("backend crashed here")


if __name__ == "__main__":
    main()
