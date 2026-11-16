"""Diagnostics: an "About / Support" window with capabilities, counters and a support bundle.

What it teaches
  * ``Application.capabilities()`` for feature detection (``features[name]["available"]``)
  * ``Application.desktop_preferences()`` (colour scheme, reduced motion, high contrast)
  * ``Application.host_diagnostics()`` and the SDK recorder (``nativehtmlkit.diagnostics``):
    loss and failure counters
  * ``Document.diagnostics()`` (CSS/resource notes for one document)
  * ``export_support_bundle`` (a local, redacted ZIP; nothing is uploaded)

Run:  python examples/diagnostics.py [OUTPUT_FOLDER]      (default: the temporary folder)
Tip:  set NATIVEHTMLKIT_DIAGNOSTICS=trace (or run ``nativehtmlkit-python --diagnostics trace ...``)
      to record callback and request timing in the bundle.
"""
from __future__ import annotations

import html
import platform
import sys
import tempfile
import time
from pathlib import Path

import nativehtmlkit
from nativehtmlkit import Application, Document, diagnostics, export_support_bundle

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { font-family: system-ui, sans-serif; margin: 18px; font-size: 14px; }
  h2 { font-size: 16px; margin: 18px 0 6px; }
  table { border-collapse: collapse; }
  td, th { text-align: left; padding: 2px 12px 2px 0; vertical-align: top; }
  td.yes { color: #2e7d32; } td.no { color: #8a1c1c; }
  #bundle { font-family: monospace; font-size: 12px; }
</style></head>
<body>
  <h2>Host</h2><table id="host"></table>
  <h2>Features</h2><table id="features"></table>
  <h2>Desktop preferences</h2><table id="prefs"></table>
  <h2>Connection counters</h2><table id="counters"></table>
  <h2>Support</h2>
  <p><button id="refresh">Refresh</button> <button id="export">Save support bundle</button></p>
  <p id="bundle" role="status"></p>
</body></html>"""

FEATURES = ("clipboard_text", "file_dialogs", "external_open", "incoming_drop", "ime", "accessibility")


def rows(pairs: list[tuple[str, object]]) -> str:
    """Values from the host are data: always escaped, never trusted as markup."""
    out = []
    for name, value in pairs:
        css = (' class="yes"' if value else ' class="no"') if isinstance(value, bool) else ""
        text = "unknown" if value is None else str(value)
        out.append(f"<tr><th>{html.escape(name)}</th><td{css}>{html.escape(text)}</td></tr>")
    return "".join(out)


class SupportWindow:
    def __init__(self, app: Application, document: Document, output: Path):
        self.app, self.document, self.output = app, document, output
        document.on("click", lambda _event: self.refresh(), element="refresh")
        document.on("click", lambda _event: self.export(), element="export")
        self.refresh()

    def refresh(self) -> dict:
        caps = self.app.capabilities()
        features = caps.get("features", {})
        prefs = self.app.desktop_preferences()
        host = self.app.host_diagnostics()
        recorder = diagnostics.recorder()
        summary = recorder.summary()
        failures = sum(1 for r in recorder.history() if r.get("event") == "callback.failed")
        counters = {
            "Host dropped notifications": host.get("dropped_notifications"),
            "SDK dropped notifications": self.app.rpc.dropped_notifications,
            "Pending host jobs": host.get("pending_jobs"),
            "Callback failures": failures,
            "SDK records (dropped)": f"{summary['records']} ({summary['dropped']})",
            "Document diagnostics": len(self.document.diagnostics().get("diagnostics", [])),
        }
        self.document.batch([
            {"op": "replace_children_html", "element": "host", "html": rows([
                ("Platform", caps.get("platform")), ("Native session", caps.get("native")),
                ("Headless", caps.get("headless")), ("Renderer", caps.get("renderer")),
                ("CSS profile", caps.get("css_profile")), ("Max windows", caps.get("max_windows")),
                ("Python", f"{platform.python_implementation()} {platform.python_version()}"),
                ("SDK", nativehtmlkit.__version__)])},
            {"op": "replace_children_html", "element": "features", "html": rows(
                [(name, bool(features.get(name, {}).get("available"))) for name in FEATURES])},
            {"op": "replace_children_html", "element": "prefs", "html": rows([
                ("Source", prefs.get("source")), ("Colour scheme", prefs.get("color_scheme")),
                ("Reduced motion", prefs.get("reduced_motion")), ("High contrast", prefs.get("high_contrast"))])},
            {"op": "replace_children_html", "element": "counters", "html": rows(list(counters.items()))},
        ])
        return counters

    def export(self) -> Path | None:
        target = self.output / f"nativehtmlkit-support-{time.strftime('%Y%m%d-%H%M%S')}.zip"
        try:
            path = export_support_bundle(target, overwrite=True)
        except (OSError, ValueError) as error:
            self.document.set_text("bundle", f"Could not save the bundle: {error}")
            return None
        self.document.set_text("bundle", f"Saved {path} ({path.stat().st_size} bytes). Attach it to a bug report.")
        return path


def build(app: Application, output: Path) -> SupportWindow:
    window = app.open_html(PAGE, title="About and support", width=760, height=640)
    return SupportWindow(app, window.document, output)


def main() -> None:
    with Application.start(name="Diagnostics") as app:
        output = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.gettempdir())
        build(app, output)
        app.run()


if __name__ == "__main__":
    main()
