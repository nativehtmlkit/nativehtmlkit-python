"""Settings dialog: an HTML <dialog> with a form, a help popover and saved preferences.

What it teaches
  * ``show_dialog`` / ``close_dialog`` with a return value, and the ``close`` event that reports it
  * Escape (a native close request) and a Cancel button that both leave settings unchanged
  * ``toggle_popover`` for lightweight help
  * applying a colour scheme with ``set_environment`` so ``@media (prefers-color-scheme)`` rules switch
  * saving settings to JSON and restoring them at start-up

Run:  python examples/settings_dialog.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from nativehtmlkit import Application, Window

APP_ID = "org.nativehtmlkit.examples.settings"
DEFAULTS = {"theme": "system", "font_size": "medium", "autosave": True, "display_name": ""}
FONT_SIZES = {"small": "13px", "medium": "15px", "large": "18px"}

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
  :root { --bg:#f5f6fa; --card:#ffffff; --text:#1c2230; --muted:#6a7386; --accent:#3a63d8; }
  @media (prefers-color-scheme: dark) { :root { --bg:#12161f; --card:#1c2230; --text:#e6eaf3; --muted:#9aa3b6; --accent:#86a6ff; } }
  body { margin:0; background:var(--bg); color:var(--text); font-family:sans-serif; }
  main { max-width:620px; margin:30px auto; padding:0 20px; }
  .card { background:var(--card); border-radius:10px; padding:18px 22px; }
  button { padding:8px 14px; border:0; border-radius:6px; background:var(--accent); color:#fff; cursor:pointer; }
  button.secondary { background:transparent; color:var(--muted); border:1px solid var(--muted); }
  dialog { border:0; border-radius:12px; padding:22px; width:380px; background:var(--card); color:var(--text); }
  dialog label { display:block; margin:12px 0 4px; }
  dialog input[type=text], dialog select { width:100%; box-sizing:border-box; padding:7px; }
  .actions { display:flex; justify-content:flex-end; gap:8px; margin-top:20px; }
  #help { max-width:260px; padding:12px; border-radius:8px; border:1px solid var(--muted); background:var(--card); color:var(--text); }
  #status { color:var(--muted); }
</style></head>
<body id="body"><main>
  <h1 id="greeting">Hello</h1>
  <div class="card">
    <p>This window applies the saved preferences. Open the settings to change them.</p>
    <button id="open-settings">Settings…</button> <button id="help-button" class="secondary">?</button>
    <p id="status">Settings loaded.</p>
  </div>
  <div id="help" popover>Theme "System" follows the desktop. Settings are stored as JSON in the
    application's data directory.</div>
  <dialog id="settings">
    <h2>Settings</h2>
    <form id="settings-form">
      <label for="display_name">Display name</label>
      <input id="display_name" name="display_name" type="text" maxlength="40">
      <label for="theme">Theme</label>
      <select id="theme" name="theme"><option value="system">System</option>
        <option value="light">Light</option><option value="dark">Dark</option></select>
      <label for="font_size">Text size</label>
      <select id="font_size" name="font_size"><option value="small">Small</option>
        <option value="medium">Medium</option><option value="large">Large</option></select>
      <label><input id="autosave" name="autosave" type="checkbox"> Save documents automatically</label>
      <div class="actions">
        <button id="cancel" type="button" class="secondary">Cancel</button>
        <button id="save" type="submit">Save</button>
      </div>
    </form>
  </dialog>
</main></body></html>"""


def load_settings(path: Path) -> dict:
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stored = {}
    return {key: stored.get(key, default) for key, default in DEFAULTS.items()}


class SettingsWindow:
    def __init__(self, window: Window, store: Path):
        self.document = doc = window.document
        self.store = store
        self.settings = load_settings(store)
        self.outcome = "cancel"
        self.apply()
        doc.on("click", lambda _e: self.open(), element="open-settings")
        doc.on("click", lambda _e: doc.toggle_popover("help"), element="help-button")
        doc.on("click", lambda _e: doc.close_dialog("settings", "cancel"), element="cancel")
        doc.on("submit", self._on_save, element="settings-form")
        doc.on("close", self._on_close, element="settings")   # after any way of closing

    def open(self) -> None:
        """Copy the current settings into the form, then show it as a modal dialog."""
        doc, s = self.document, self.settings
        doc.set_value("display_name", s["display_name"])        # set_value: plain text, no markup
        doc.set_selected_values("theme", [s["theme"]])
        doc.set_selected_values("font_size", [s["font_size"]])
        doc.set_checked("autosave", bool(s["autosave"]))
        self.outcome = "cancel"
        doc.show_dialog("settings", modal=True)
        doc.focus("display_name")

    def apply(self) -> None:
        s, doc = self.settings, self.document
        # "light"/"dark" override the desktop; "system" removes the override again.
        doc.set_environment(color_scheme=s["theme"])
        doc.set_attribute("body", "style", f"font-size:{FONT_SIZES[s['font_size']]}")
        doc.set_text("greeting", f"Hello, {s['display_name']}" if s["display_name"] else "Hello")

    def _on_save(self, _event: dict) -> None:
        entries = {e["name"]: e.get("value", "") for e in self.document.form_data("settings-form")["entries"]}
        self.settings = {
            "display_name": entries.get("display_name", "").strip(),
            "theme": entries.get("theme", "system"),
            "font_size": entries.get("font_size", "medium"),
            "autosave": "autosave" in entries,       # unchecked boxes are absent from form data
        }
        self.store.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.store.with_name(self.store.name + ".tmp")
        temporary.write_text(json.dumps(self.settings, indent=2), encoding="utf-8")
        os.replace(temporary, self.store)
        self.apply()
        self.outcome = "saved"
        self.document.close_dialog("settings", "saved")

    def _on_close(self, event: dict) -> None:
        # Fired for close_dialog() and for a native close request (Escape). event["return_value"]
        # is the dialog's returnValue; as in HTML a close request does not reset it, so this
        # controller tracks the outcome of the current opening itself.
        self.document.set_text("status", "Settings saved." if self.outcome == "saved" else "No changes made.")


def build(app: Application, store: Path) -> SettingsWindow:
    return SettingsWindow(app.open_html(PAGE, title="Settings demo", width=680, height=520), store)


def main() -> None:
    with Application.start(name="Settings demo", app_id=APP_ID) as app:
        store = Path(app.rpc.call("desktop.paths")["config"]) / "settings.json"
        build(app, store)
        app.run()


if __name__ == "__main__":
    main()
