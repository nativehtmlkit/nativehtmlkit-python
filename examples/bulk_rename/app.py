"""Bulk rename: rename many files with find/replace, a live preview and undo.

This is the finished app of the tutorial docs/tutorials/bulk-rename.md.

What it teaches
  * an app split into index.html + style.css + app.py (``Application.open_file``)
  * a pure planning function that is easy to test without a window
  * live preview on ``input``/``change`` events of a whole form
  * the native folder picker with a capability check and an ``RpcError`` fallback
  * a confirmation ``<dialog>``, per-file error handling, and undo

Run:  python examples/bulk_rename/app.py [FOLDER]
In regular-expression mode the replacement uses Python syntax: ``\\1`` or ``\\g<1>`` for groups.
"""
from __future__ import annotations

import html
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from nativehtmlkit import Application, Document, RpcError

HERE = Path(__file__).resolve().parent
WINDOWS = sys.platform == "win32"
INVALID_CHARACTERS = set('<>:"/\\|?*' + "".join(map(chr, range(32)))) if WINDOWS else {"/", "\0"}


# ---------------------------------------------------------------------------- planning (no UI)

@dataclass
class Row:
    old: str
    new: str
    status: str = "unchanged"     # unchanged | rename | conflict | invalid | error
    note: str = ""


def plan_renames(names: list[str], find: str, replace: str, *, regex: bool, match_case: bool) -> list[Row]:
    """One row per file name; never touches the disk."""
    rows = [Row(name, name) for name in names]
    if not find:
        return rows
    try:
        pattern = re.compile(find if regex else re.escape(find), 0 if match_case else re.IGNORECASE)
        # Plain-text mode: the replacement is literal text (a function bypasses \1 processing).
        replacement = replace if regex else (lambda _match: replace)
        new_names = [pattern.sub(replacement, name) for name in names]
    except (re.error, IndexError) as error:          # bad pattern, or \3 with only two groups
        for row in rows:
            row.status, row.note = "error", f"Invalid pattern: {error}"
        return rows

    def key(name: str) -> str:                       # Windows file names are case-insensitive
        return name.casefold() if WINDOWS else name

    existing = {key(name) for name in names}
    claimed: set[str] = set()
    for row, new in zip(rows, new_names):
        row.new = new
        if new == row.old:
            continue
        if not new or new in (".", "..") or INVALID_CHARACTERS & set(new):
            row.status, row.note = "invalid", "Not a valid file name"
        elif (key(new) in existing and key(new) != key(row.old)) or key(new) in claimed:
            row.status, row.note = "conflict", "Name already used"
        else:
            row.status = "rename"
            claimed.add(key(new))
    return rows


# ---------------------------------------------------------------------------------- the app

class BulkRename:
    def __init__(self, app: Application, window):
        self.app, self.window, self.document = app, window, window.document
        self.folder: Path | None = None
        self.names: list[str] = []
        self.plan: list[Row] = []
        self.undo_steps: list[tuple[str, str]] = []
        doc = self.document
        if not app.capabilities().get("features", {}).get("file_dialogs", {}).get("available"):
            doc.set_attribute("browse", "disabled", "")
        # Live preview: every keystroke or checkbox change in the rule form.
        doc.on("input", lambda _event: self.update_preview(), element="rule")
        doc.on("change", lambda _event: self.update_preview(), element="rule")
        # Enter in a rule field submits the form: treat it as "update preview", nothing else.
        doc.on("submit", lambda _event: self.update_preview(), element="rule")
        doc.on("click", lambda _event: self.open_folder(doc.get_value("folder")), element="load")
        doc.on("click", lambda _event: self.browse(), element="browse")
        doc.on("click", lambda _event: self.ask_confirmation(), element="apply")
        # Decide in the button handlers, not in the dialog's close event: a <dialog> keeps its
        # previous return value when the user dismisses it with Escape.
        doc.on("click", lambda _event: self.confirm(False), element="confirm-no")
        doc.on("click", lambda _event: self.confirm(True), element="confirm-yes")
        doc.on("click", lambda _event: self.undo(), element="undo")

    def set_summary(self, text: str) -> None:
        self.document.set_text("summary", text)

    def set_enabled(self, element: str, enabled: bool) -> None:
        if enabled:
            self.document.remove_attribute(element, "disabled")
        else:
            self.document.set_attribute(element, "disabled", "")

    def update_preview(self) -> None:
        doc = self.document
        self.plan = plan_renames(self.names, doc.get_value("find"), doc.get_value("replace"),
                                 regex=doc.get_checked("regex"), match_case=doc.get_checked("case"))
        # File names are untrusted text: escape every cell. The status class comes from a fixed set.
        cells = "".join(f'<tr class="{row.status}"><td>{html.escape(row.old)}</td><td>{html.escape(row.new)}</td>'
                        f'<td>{html.escape(row.note or row.status)}</td></tr>' for row in self.plan)
        count = sum(row.status == "rename" for row in self.plan)
        blocked = sum(row.status in ("conflict", "invalid", "error") for row in self.plan)
        summary = f"{len(self.names)} file(s), {count} to rename" + (f", {blocked} skipped" if blocked else "")
        doc.batch([
            {"op": "replace_children_html", "element": "preview", "html": cells},
            {"op": "set_text", "element": "summary", "text": summary},
            {"op": "set_text", "element": "apply", "text": f"Rename {count}"},
        ])
        self.set_enabled("apply", count > 0)

    def update_file_list(self) -> None:
        self.names = sorted(entry.name for entry in self.folder.iterdir() if entry.is_file())
        self.update_preview()

    def open_folder(self, path: str) -> None:
        if not path or not Path(path).is_dir():
            self.set_summary("That folder does not exist.")
            return
        self.folder = Path(path).resolve()
        self.document.set_value("folder", str(self.folder))
        self.set_undo([])
        self.update_file_list()

    def browse(self) -> None:
        def done(future) -> None:
            try:
                result = future.result()
            except RpcError as error:        # -32001: no dialog service in this session
                self.set_summary("Native file dialogs are not available in this session."
                                 if error.code == -32001 else f"The folder dialog failed (error {error.code}).")
                return
            if not result["cancelled"]:
                self.open_folder(result["paths"][0])
        # wait=False keeps the event thread free while the dialog is open.
        self.window.choose_folder(title="Folder with files to rename", wait=False).add_done_callback(done)

    def set_undo(self, steps: list[tuple[str, str]]) -> None:
        self.undo_steps = steps
        self.set_enabled("undo", bool(steps))

    def ask_confirmation(self) -> None:
        count = sum(row.status == "rename" for row in self.plan)
        self.document.set_text("confirm-text", f"Rename {count} file(s) in {self.folder}?")
        self.document.show_dialog("confirm")

    def confirm(self, yes: bool) -> None:
        self.document.close_dialog("confirm", "")
        if yes:
            self.rename()

    def rename(self) -> None:
        done, failed = [], 0
        for row in (r for r in self.plan if r.status == "rename"):
            source, target = self.folder / row.old, self.folder / row.new
            try:
                # os.rename silently replaces an existing file on Linux: refuse that ourselves.
                if target.exists() and not (WINDOWS and row.old.casefold() == row.new.casefold()):
                    raise FileExistsError(target)
                os.rename(source, target)
                done.append((row.old, row.new))
            except OSError:                   # in use, permission denied, or changed since the preview
                failed += 1
        self.set_undo(done)
        self.update_file_list()
        message = f"Renamed {len(done)} file(s)."
        if failed:
            message += f" {failed} failed (in use, permission denied or changed)."
        self.set_summary(message)

    def undo(self) -> None:
        if not self.undo_steps:
            return
        restored = 0
        # Reverse order, so chains such as a->b, b->c are undone correctly.
        for old, new in reversed(self.undo_steps):
            try:
                os.rename(self.folder / new, self.folder / old)
                restored += 1
            except OSError:
                pass
        self.set_undo([])
        self.update_file_list()
        self.set_summary(f"Restored {restored} file name(s).")


def build(app: Application, folder: str | None = None) -> BulkRename:
    # Relative URLs in index.html (style.css) resolve against the file's folder.
    window = app.open_file(HERE / "index.html", title="Bulk rename", width=900, height=620,
                           min_width=640, min_height=400)
    tool = BulkRename(app, window)
    if folder:
        tool.open_folder(folder)
    return tool


def main() -> None:
    with Application.start(name="Bulk rename") as app:
        build(app, sys.argv[1] if len(sys.argv) > 1 else None)
        app.run()


if __name__ == "__main__":
    main()
