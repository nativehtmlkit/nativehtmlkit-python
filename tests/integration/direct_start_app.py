"""Direct start (``python direct_start_app.py``): Application.start() two-process bootstrap."""
import os

from it_support import check, emit, quit_when_ready

from nativehtmlkit import Application

# Documented behaviour: top-level code runs in the launcher AND in the backend.
import sys
emit("toplevel", role="backend" if os.environ.get("UI4ME_ENDPOINT") else "launcher", pid=os.getpid(),
     argv=sys.argv[1:])


def main():
    with Application.start(name="IT direct " + os.environ.get("NHK_IT_MARKER", "")) as app:
        check("direct.connected", app.rpc.hello.get("protocol_version") == 1)
        check("env.wire_vars_scrubbed", not [k for k in os.environ if k in
          ("UI4ME_ENDPOINT", "UI4ME_TOKEN", "UI4ME_APP_ID", "UI4ME_PROTOCOL_VERSION", "UI4ME_DIRECT_START")])
        window = app.open_html("<p id='s'>direct</p>", title="IT direct")
        check("direct.document", window.document.get_text("s") == "direct")
        quit_when_ready(app, delay=0.2)
        app.run()


if __name__ == "__main__":
    main()
