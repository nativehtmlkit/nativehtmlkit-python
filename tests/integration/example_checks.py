"""Behaviour checks for the applications in examples/, run inside the REAL Core host.

The driver (test_example_behaviour.py) starts ``python -m nativehtmlkit run
example_checks:<name>`` with examples/ on PYTHONPATH. Each entry point imports one example,
calls its ``build(...)`` function, drives it through the example's own action methods or the
public SDK (``request_submit`` and ``set_value`` work headless; there is no synthetic pointer or
keyboard input), reads the resulting DOM state back through the public API and reports every
assertion with ``it_support.check``. It then requests an orderly quit.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from it_support import Guard, check, emit, quit_when_ready

from nativehtmlkit import RpcError


def _wait(predicate, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def _scratch() -> Path:
    return Path(tempfile.mkdtemp(prefix="nhk-example-"))


def _count(document, selector: str) -> int:
    return document.query_nodes(selector)["total"]


def _headless(app) -> bool:
    return bool(app.capabilities().get("headless"))


# --------------------------------------------------------------------------- todo
def todo(app):
    import todo as example

    store = _scratch() / "todos.json"
    store.write_text(json.dumps([{"id": 4, "title": "Saved earlier", "done": True}]), encoding="utf-8")
    controller = example.build(app, store)
    doc = controller.document
    with Guard("todo"):
        check("todo.loads_saved_file", doc.get_text("todo-4-text") == "Saved earlier"
              and doc.get_checked("todo-4-done") is True)
        doc.set_value("new-title", "Buy milk")
        result = doc.request_submit("new-form", submitter="add")
        check("todo.submit_accepted", result.get("submitted") is True, result=result)
        check("todo.add_via_form_submit", _wait(lambda: doc.command("has_element", element="todo-5")["exists"]))
        check("todo.input_cleared", doc.get_value("new-title") == "")
        check("todo.count_text", doc.get_text("count") == "1 item left", text=doc.get_text("count"))
        controller.add("<b>not bold</b> & more")
        check("todo.untrusted_text_escaped", doc.get_text("todo-6-text") == "<b>not bold</b> & more"
              and _count(doc, "#todo-6-text b") == 0)
        controller.toggle(5, True)
        check("todo.toggle_marks_done", "done" in doc.node("todo-5").inspect()["attributes"].get("class", ""))
        controller.start_edit(6)
        check("todo.edit_mode_input", doc.get_value("edit-title") == "<b>not bold</b> & more")
        check("todo.edit_mode_focus", (doc.focused_element() or {}).get("element") == "edit-title")
        doc.set_value("edit-title", "Renamed")
        doc.request_submit("edit-form-6")
        check("todo.edit_via_form_submit", _wait(lambda: doc.command("has_element", element="todo-6-text")["exists"]
                                                  and doc.get_text("todo-6-text") == "Renamed"))
        controller.set_filter("active")
        check("todo.filter_active", _count(doc, "#todos li") == 1 and doc.get_text("todo-6-text") == "Renamed")
        check("todo.filter_button_state", "active" in doc.node("filter-active").inspect()["attributes"]["class"])
        controller.set_filter("all")
        controller.clear_done()
        check("todo.clear_done", _count(doc, "#todos li") == 1)
        controller.delete(6)
        check("todo.delete_shows_empty_state", doc.get_text("todos") == "Nothing here.")
        controller.add("Persist me")
        saved = json.loads(store.read_text(encoding="utf-8"))
        check("todo.persisted_json", [t["title"] for t in saved] == ["Persist me"], saved=saved)
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- tutorial step 4
def tutorial_step4(app):
    from tutorial import step4_edit_keyboard as example

    todo = example.TodoApp(app.open_html(example.PAGE, title="Tutorial step 4"))
    doc = todo.doc
    with Guard("tutorial"):
        doc.set_value("new-title", "Write docs")
        doc.request_submit("new-form")
        check("tutorial.add", _wait(lambda: _count(doc, "#todos li") == 1))
        todo.on_click({"element": "todo-1-edit"})
        doc.set_value("edit-title", "Write better docs")
        doc.request_submit("edit-form-1")
        check("tutorial.edit", _wait(lambda: doc.get_text("todos") == "Write better docsEditDelete"))
        todo.on_click({"element": "todo-1-edit"})
        check("tutorial.edit_mode", doc.get_value("edit-title") == "Write better docs")
        todo.on_key({"key": "Escape"})
        check("tutorial.escape_cancels", doc.get_text("todos") == "Write better docsEditDelete" and todo.editing is None)
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- signup form
def signup_form(app):
    import signup_form as example

    form = example.build(app)
    doc = form.document
    with Guard("signup"):
        result = form.submit()
        check("signup.empty_form_not_submitted", result.get("submitted") is False, result=result)
        # Seven required controls. Core 1.0.3 in headless test mode does not report the required
        # checkbox ("terms") as invalid; an interactive desktop host reports all seven.
        expected = (6, 7)
        check("signup.invalid_events_listed", _wait(lambda: len(form.errors) in expected), errors=form.errors)
        check("signup.error_summary_rendered", _wait(lambda: _count(doc, "#errors li") == len(form.errors)))
        for element, value in (("name", "Ada <Lovelace>"), ("email", "ada@example.org"),
                               ("password", "correct horse"), ("confirm", "wrong horse"), ("age", "36")):
            doc.set_value(element, value)
        doc.set_selected_values("country", ["fr"])
        doc.set_checked("terms", True)
        form.errors.clear()
        result = form.submit()
        check("signup.password_mismatch_blocks", result.get("submitted") is False
              and _wait(lambda: form.errors == ["Repeat password: The passwords do not match."]), errors=form.errors)
        doc.set_value("confirm", "correct horse")
        for topic in doc.query_nodes("input[name=topic]")["nodes"][:2]:
            doc.node_batch([{"op": "set_attribute", "node": topic["node"], "name": "checked", "value": ""}])
        result = form.submit()
        check("signup.valid_form_submitted", result.get("submitted") is True, result=result)
        check("signup.account_recorded", _wait(lambda: len(form.accounts) == 1 and doc.get_value("name") == ""),
              accounts=form.accounts)
        account = form.accounts[0] if form.accounts else {}
        check("signup.form_data_values", account.get("name") == "Ada <Lovelace>" and account.get("country") == "fr"
              and account.get("topics") == ["news", "releases"], account=account)
        check("signup.result_escaped", doc.get_text("result").startswith("Welcome, Ada <Lovelace>!")
              and _count(doc, "#result Lovelace") == 0)
        check("signup.form_reset_after_success", doc.get_value("name") == "")
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- log viewer
def log_viewer(app):
    import log_viewer as example

    log = _scratch() / "service.log"
    log.write_text("INFO service started\nINFO listening on port 8080\n<script>not markup</script>\npartial", encoding="utf-8")
    viewer = example.build(app, log)
    doc = viewer.document
    with Guard("log"):
        check("log.window_title", app.rpc.call("window.get", {"window_id": doc.window.id})["title"] == "Log - service.log")
        check("log.file_shown", doc.get_text("file") == str(log.resolve()))
        thread = viewer.start()
        check("log.initial_lines", _wait(lambda: viewer.line_count == 3, 10), count=viewer.line_count)
        check("log.partial_line_waits", "partial" not in doc.get_text("log"))
        with log.open("a", encoding="utf-8") as handle:
            handle.write(" line done\nWARN disk 91% full\nERROR backup job failed\n")
        check("log.appended_lines", _wait(lambda: viewer.line_count == 6, 10), count=viewer.line_count)
        check("log.partial_completed", "partial line done" in doc.get_text("log"))
        check("log.error_highlighted", _count(doc, "#log li.error") == 1)
        check("log.warning_highlighted", _count(doc, "#log li.warn") == 1)
        third = doc.query_nodes("#log li")["nodes"][2]["node"]
        markup = doc.command("get_html", node=third)["html"]
        check("log.lines_escaped", markup == "&lt;script&gt;not markup&lt;/script&gt;", html=markup)
        check("log.status", _wait(lambda: doc.get_text("status").startswith("6 lines shown. Last check ")))
        doc.set_checked("paused", True)
        time.sleep(0.6)
        with log.open("a", encoding="utf-8") as handle:
            handle.write("INFO while paused\n")
        time.sleep(1.2)
        check("log.pause_holds_lines", viewer.line_count == 6)
        doc.set_checked("paused", False)
        check("log.resume_catches_up", _wait(lambda: viewer.line_count == 7, 5))
        viewer.add_lines("\n".join(f"DEBUG line {i}" for i in range(example.MAX_LINES + 20)))
        check("log.bounded", _count(doc, "#log li") == example.MAX_LINES and viewer.line_count == example.MAX_LINES)
        check("log.oldest_trimmed", "service started" not in doc.get_text("log"))
        viewer.clear()
        check("log.clear", _count(doc, "#log li") == 0 and viewer.line_count == 0)
        log.write_text("INFO rotated\n", encoding="utf-8")       # truncated: shorter than the offset
        check("log.truncation_restarts", _wait(lambda: viewer.line_count == 1 and "rotated" in doc.get_text("log"), 5))
        viewer.stopped.set()
        thread.join(3)
        check("log.thread_stops", not thread.is_alive())
        viewer.path = log.with_name("missing.log")
        viewer.poll_once()
        check("log.read_error_reported", doc.get_text("status").startswith("Cannot read the file: ")
              and doc.get_text("status").endswith(" Retrying..."), text=doc.get_text("status"))
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- settings dialog
def settings_dialog(app):
    import settings_dialog as example

    store = _scratch() / "settings.json"
    settings = example.build(app, store)
    doc = settings.document
    with Guard("settings"):
        check("settings.defaults_applied", doc.computed_style(["font-size"], "sample")["properties"]["font-size"]["value"] == "15px")
        settings.show()
        check("settings.dialog_open", doc.command("get_dialog", element="settings")["open"] is True)
        check("settings.form_prefilled", doc.get_value("size") == "15"
              and [o["value"] for o in doc.options("theme") if o["selected"]] == ["system"])
        doc.set_selected_values("theme", ["dark"])
        doc.set_value("size", "40")
        result = doc.request_submit("settings-form", submitter="apply")
        check("settings.max_blocks_submit", result.get("submitted") is False, result=result)
        doc.set_value("size", "18")
        doc.set_checked("motion", True)
        result = doc.request_submit("settings-form", submitter="apply")
        check("settings.valid_submit", result.get("submitted") is True, result=result)
        check("settings.saved_reported", _wait(lambda: doc.get_text("saved") == f"Settings saved to {store}"))
        environment = doc.environment()
        check("settings.environment_applied", environment["color_scheme"] == "dark"
              and environment["reduced_motion"] == "reduce", environment=environment)
        size = doc.computed_style(["font-size"], "sample")["properties"]["font-size"]["value"]
        check("settings.stylesheet_replaced", size == "18px" and len(doc.stylesheets()) == 2, size=size)
        dialog = doc.command("get_dialog", element="settings")
        check("settings.closed_with_return_value", dialog["open"] is False and dialog["return_value"] == "saved")
        saved = json.loads(store.read_text(encoding="utf-8"))
        check("settings.saved_json", saved == {"theme": "dark", "size": 18, "motion": True}, saved=saved)
        settings.show()
        settings.cancel()
        check("settings.cancel", doc.get_text("saved") == "Settings unchanged."
              and doc.command("get_dialog", element="settings")["return_value"] == "cancelled")
        check("settings.help_popover_toggles", doc.toggle_popover("help-tip") is True and doc.toggle_popover("help-tip") is False)
        check("settings.reload_from_disk", example.read_settings(store) == saved)
        store.write_text("{not json", encoding="utf-8")
        check("settings.unreadable_file_ignored", example.read_settings(store) == example.DEFAULTS)
        check("settings.default_path", example.default_settings_path().parts[-2:] == ("NativeHTMLKit-Examples", "settings.json"))
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- file viewer
def file_viewer(app):
    import file_viewer as example

    viewer = example.build(app)
    doc = viewer.document
    folder = _scratch()
    (folder / "notes.md").write_text("# Notes\n<script>alert(1)</script>\n", encoding="utf-8")
    (folder / "data.json").write_text('{"a": 1}', encoding="utf-8")
    (folder / "image.png").write_bytes(b"\x89PNG")
    (folder / "latin1.txt").write_bytes("caf\xe9".encode("latin-1"))
    with Guard("files"):
        viewer.show_folder(folder)
        check("files.folder_lists_text_files", _count(doc, "#files li") == 3
              and doc.get_text("files") == "data.jsonlatin1.txtnotes.md", text=doc.get_text("files"))
        viewer._on_file_click({"element": "file-2"})
        check("files.load_into_textarea", doc.get_value("editor") == "# Notes\n<script>alert(1)</script>\n")
        check("files.window_title", app.rpc.call("window.get", {"window_id": viewer.window.id})["title"].startswith("notes.md"))
        viewer.load(folder / "latin1.txt")
        check("files.non_utf8_reported", doc.get_text("status") == "latin1.txt is not UTF-8 text.")
        doc.set_value("editor", "edited\n")
        viewer.save(folder / "out.txt")
        check("files.save_writes_file", (folder / "out.txt").read_text(encoding="utf-8") == "edited\n")
        if _headless(app):
            future = viewer.ask_open()
            error = future.exception(10)
            check("files.dialog_unsupported_headless", isinstance(error, RpcError) and error.code == -32001)
            check("files.dialog_status_message", _wait(lambda: doc.get_text("status")
                                                       == "Native file dialogs are not available in this session."))
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- window manager
def multi_window(app):
    import window_manager as example

    manager = example.build(app)
    doc = manager.document
    shutdown = []
    app.on_shutdown(lambda: emit("info", name="window_manager_shutdown") or shutdown.append(1))

    def after_ready():
        # Closing windows is exercised after app.ready: before it, closing the LAST usable window
        # cancels start-up (Core protocol §7).
        with Guard("windows"):
            first, second = manager.new_note(), manager.new_note()
            check("windows.three_listed", _count(doc, "#rows tr") == 3)
            check("windows.host_window_list", len(app.rpc.call("window.list")) == 3)
            doc.set_value("rename-to", "Shopping <list>")
            manager._on_row_click({"element": f"row-{first.window.id}-rename"})
            check("windows.rename_sets_title", first.window.state()["title"] == "Shopping <list>")
            check("windows.title_escaped_in_table", "Shopping <list>" in doc.get_text("rows"))
            manager._on_row_click({"element": f"row-{first.window.id}-grow"})
            state = first.window.state()
            check("windows.resize", (state["width"], state["height"]) == (640, 480), state=state)
            second.mark_dirty()
            manager._on_row_click({"element": f"row-{second.window.id}-close"})
            check("windows.dirty_note_vetoes_close", _wait(lambda: "shown" in second.document.node("warning")
                                                           .inspect()["attributes"].get("class", "")))
            check("windows.dirty_note_still_open", not second.window.closed)
            second.discard_and_close()
            check("windows.discard_closes", _wait(lambda: second.window.closed))
            check("windows.table_updated_on_closed", _wait(lambda: _count(doc, "#rows tr") == 2))
            check("windows.events_logged", "close_requested" in doc.get_text("events"))
            first.mark_dirty()
            manager.main.request_close()
            check("windows.main_close_blocked_by_dirty_note",
                  _wait(lambda: "unsaved changes" in doc.get_text("status")) and not manager.main.closed)
            first.save()
            manager.main.request_close()   # main closed with a note open -> request_quit()
            check("windows.main_close_quits_app", _wait(lambda: bool(shutdown), 10))
    quit_when_ready(app, delay=0.2, then=after_ready)


# --------------------------------------------------------------------------- live chart
def live_chart(app):
    import live_chart as example

    chart = example.build(app)
    with Guard("chart"):
        frame = example.render([0.0, 0.5, 1.0], chart.background)
        check("chart.frame_size", len(frame) == example.WIDTH * example.HEIGHT * 4)
        top_right = ((0 * example.WIDTH) + example.WIDTH - 1) * 4
        check("chart.line_pixel_drawn", bytes(frame[top_right:top_right + 4]) == bytes(example.LINE))
        result = chart.bitmap.present(frame)
        check("chart.present_acknowledged", result.get("presented_to_engine") is True, result=result)
        chart.start()
        check("chart.producer_presents_frames", _wait(lambda: chart.frames >= 15, 10), frames=chart.frames)
        check("chart.stats_text_updated", _wait(lambda: chart.document.get_text("frames") != "0"))
        chart.running.clear()
        time.sleep(0.3)
        frames = chart.frames
        time.sleep(0.3)
        check("chart.stop_stops_frames", chart.frames == frames)
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- text toolbox
def clipboard_tool(app):
    import text_toolbox as example

    box = example.build(app)
    doc = box.document
    with Guard("toolbox"):
        check("toolbox.window_title", app.rpc.call("window.get", {"window_id": box.window.id})["title"] == "Clipboard tool")
        doc.set_value("text", "b\na\nB\na")
        box.transform("sort")
        check("toolbox.sort_lines", doc.get_value("text") == "a\na\nb\nB")
        box.transform("unique")
        check("toolbox.unique_lines", doc.get_value("text") == "a\nb\nB")
        box.transform("upper")
        check("toolbox.upper", doc.get_value("text") == "A\nB\nB")
        doc.set_value("text", '{"x": [1, 2]}')
        box.transform("json")
        check("toolbox.json_pretty", doc.get_value("text") == '{\n  "x": [\n    1,\n    2\n  ]\n}')
        doc.set_value("text", "{not json")
        box.transform("json")
        check("toolbox.json_error_reported", doc.get_text("status").startswith("Cannot apply “json”"))
        check("toolbox.stats", doc.get_text("stats").startswith("9 characters · 2 words · 1 lines"),
              stats=doc.get_text("stats"))
        box._on_toolbar({"element": "copy"})
        status = doc.get_text("status")
        if _headless(app):
            check("toolbox.clipboard_unavailable_headless", status == "Clipboard is not available in this session.",
                  text=status)
            box.open_link(example.DOCS_URL)
            check("toolbox.open_external_unavailable_headless",
                  doc.get_text("status") == "Opening links is not available in this session.")
        else:
            emit("info", name="toolbox_copy_status", value=status)
        box.open_link("file:///etc/passwd")
        check("toolbox.non_https_refused", doc.get_text("status") == "Only https links are opened.")
        check("toolbox.preferences_shown", doc.get_text("scheme") != "")
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- async jobs
async def background_jobs(app):
    import async_jobs as example

    window = await asyncio.to_thread(app.open_html, example.PAGE, title="Async jobs check")
    runner = example.JobRunner(app, window)
    doc = window.document
    with Guard("async"):
        await asyncio.to_thread(doc.set_value, "seconds", "1")
        await asyncio.to_thread(doc.request_submit, "new-job")
        for _ in range(100):
            if runner.tasks:
                break
            await asyncio.sleep(0.02)
        check("async.submit_starts_job", 1 in runner.tasks)
        slow = runner.start_job(30)
        await asyncio.sleep(0.5)
        await runner.on_click({"element": f"job-{slow}-cancel"})
        await asyncio.gather(*runner.tasks.values(), return_exceptions=True)
        check("async.job_done", runner.states.get(1) == "done", states=runner.states)
        check("async.job_cancelled", runner.states.get(slow) == "cancelled", states=runner.states)
        text = await asyncio.to_thread(doc.get_text, "summary")
        check("async.summary", text == "0 running, 1 done, 1 cancelled", text=text)
        style = (await runner.command("get_attribute", element="job-1-fill", name="style"))["value"]
        check("async.progress_complete", style == "width:100%", style=style)
        check("async.cancel_button_removed",
              not (await runner.command("has_element", element=f"job-{slow}-cancel"))["exists"])
    quit_when_ready(app, delay=0.2)
    await runner.adapter.run()


# --------------------------------------------------------------------------- checksum
# A name that would break the table if not escaped, but is legal on Windows too (no < > there).
UNSAFE_NAME = "sub/b & <x>.bin" if os.name != "nt" else "sub/b & 'x' &amp;.bin"


def checksums(app):
    import checksum as example

    tool = example.build(app)
    doc = tool.document
    folder = _scratch()
    files = {"a.txt": b"alpha", UNSAFE_NAME: bytes(range(256)) * 4000, "c.md": b""}
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    with Guard("checksum"):
        check("checksum.window_title", app.rpc.call("window.get", {"window_id": tool.window.id})["title"] == "Checksums")
        worker = tool.start(folder)
        check("checksum.worker_started", worker is not None)
        worker.join(30)
        expected = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
        check("checksum.hashes_correct", tool.results == expected)
        check("checksum.rows_rendered", _count(doc, "#results tr") == 3)
        check("checksum.names_escaped", UNSAFE_NAME in doc.get_text("results"))
        check("checksum.status_done", doc.get_text("status") == "Done: 3 of 3 file(s).", text=doc.get_text("status"))
        check("checksum.progress_full",
              doc.command("get_attribute", element="bar", name="style")["value"] == "width:100%")
        check("checksum.bad_folder", tool.start(folder / "missing") is None
              and doc.get_text("status").startswith("Not a folder"))
        tool.cancel.set()
        tool.worker = threading.Thread(target=time.sleep, args=(1.5,))   # simulate a running job
        tool.worker.start()
        check("checksum.quit_vetoed_while_busy", tool.may_quit() is False
              and "shown" in doc.node("warning").inspect()["attributes"]["class"])
        check("checksum.second_quit_allowed", tool.may_quit() is True)
        tool.worker.join()
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- data table
def data_table(app):
    import data_table as example

    records = example.sample_inventory()
    table = example.build(app, records)
    doc = table.document
    with Guard("table"):
        check("table.first_page", _count(doc, "#rows tr") == 25 and doc.get_text("page") == "Page 1 of 10")
        table.set_category("Audio")
        audio = [r for r in records if r["category"] == "Audio"]
        check("table.category_filter", doc.get_text("matches") == f"{len(audio)} of 240 records")
        table.set_category("")
        table.set_query("sku-0007")
        check("table.search", _count(doc, "#rows tr") == 1 and doc.get_text("rows").startswith("SKU-0007"))
        table.set_query("")
        table.sort_by("price")
        cheapest = min(records, key=lambda r: r["price"])
        first = doc.query_nodes("#rows tr")["nodes"][0]["element"]
        check("table.sort_ascending", first == f"row-{cheapest['sku']}", first=first)
        check("table.sorted_header_class", "sorted-asc" in doc.node("col-price").inspect()["attributes"]["class"])
        table.sort_by("price")
        first = doc.query_nodes("#rows tr")["nodes"][0]["element"]
        check("table.sort_descending", first == f"row-{max(records, key=lambda r: r['price'])['sku']}")
        table.go(+1)
        check("table.next_page", doc.get_text("page") == "Page 2 of 10")
        table.go(+100)
        check("table.page_clamped", doc.get_text("page") == "Page 10 of 10")
        table._on_row({"element": f"row-{records[0]['sku']}"})
        check("table.details_pane", doc.get_text("d-sku") == records[0]["sku"])
        table.set_query("no such product")
        check("table.empty_state", doc.get_text("rows") == "No matching records.")
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- DOM explorer
def dom_explorer(app):
    import dom_explorer as example

    explorer = example.build(app)
    doc = explorer.document
    with Guard("dom"):
        labels = [doc.node(reference=n.id).inspect() for n in explorer.items]
        check("dom.tree_lists_nodes", len(explorer.items) >= 10 and _count(doc, "#tree .item") == len(explorer.items))
        li_index = next(i for i, info in enumerate(labels) if info.get("name") == "li" and info["previous"])
        explorer.select(li_index)
        check("dom.select_highlights_anonymous_node",
              "highlight" in explorer.current.inspect()["attributes"].get("class", ""))
        explorer.uppercase()
        check("dom.uppercase_leaf", "SMALLER BINARIES" in doc.get_text("sample"), text=doc.get_text("sample"))
        explorer.move_up()
        items = [c["node"] for c in doc.node(reference=explorer.current.inspect()["parent"]).children()["children"]
                 if c["type"] == "element"]
        check("dom.move_up", items.index(explorer.current.id) == 0)
        explorer.delete()
        check("dom.delete", "SMALLER BINARIES" not in doc.get_text("sample"))
        stale = doc.node("sample")
        explorer.document.window.load_html("<p>replaced</p>")
        try:
            stale.inspect()
            check("dom.stale_after_reload", False)
        except Exception as error:
            check("dom.stale_after_reload", type(error).__name__ == "StaleDocumentError")
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- focus timer
def focus_timer(app):
    import focus_timer as example

    stats = _scratch() / "stats.json"
    timer = example.build(app, stats)
    doc = timer.document

    def after_ready():
        with Guard("timer"):
            timer.start(1.2)
            check("timer.running_title", timer.window.state()["title"].endswith("— Focus timer"))
            check("timer.finishes", _wait(lambda: timer.stats["completed"] == 1, 5))
            check("timer.sessions_text", _wait(lambda: doc.get_text("sessions") == "Completed sessions: 1"))
            check("timer.clock_zero", doc.get_text("clock") == "00:00")
            timer.start(60)
            app.request_quit()
            check("timer.quit_vetoed_while_running",
                  _wait(lambda: doc.command("get_dialog", element="confirm-quit")["open"]))
            doc.close_dialog("confirm-quit", "keep")
            timer.pause()
            check("timer.pause_keeps_remaining", 55 < timer.remaining <= 60 and not timer.running)
            app.on_shutdown(lambda: check("timer.stats_saved_on_shutdown",
                                          json.loads(stats.read_text(encoding="utf-8")) == {"completed": 1}))
    quit_when_ready(app, delay=0.2, then=after_ready)


# --------------------------------------------------------------------------- helpers for subfolder examples
def _load(relative: str, name: str):
    """Import examples/<relative> under ``name``; its folder goes on sys.path for sibling imports."""
    import importlib.util
    import sys

    path = Path(__file__).resolve().parents[2] / "examples" / relative
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _attribute(document, element: str, name: str):
    return document.command("get_attribute", element=element, name=name)["value"]


# --------------------------------------------------------------------------- hello
def hello(app):
    import hello as example

    doc = example.build(app)
    with Guard("hello"):
        check("hello.initial_text", doc.get_text("greeting") == "Type a name and press Greet.")
        doc.set_value("name", "  <b>Ada</b> ")
        example.greet(doc)
        check("hello.greeting_plain_text", doc.get_text("greeting") == "Hello, <b>Ada</b>!"
              and _count(doc, "#greeting b") == 0, text=doc.get_text("greeting"))
        doc.set_value("name", "   ")
        example.greet(doc)
        check("hello.empty_name_greets_world", doc.get_text("greeting") == "Hello, world!")
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- counter
def counter(app):
    import counter as example

    counter = example.build(app)
    doc = counter.document
    with Guard("counter"):
        counter.on_click({"element": "inc"})
        check("counter.increment_via_handler", doc.get_text("value") == "1")
        doc.set_selected_values("step", ["10"])
        check("counter.step_read_from_select", counter.step() == 10)
        for _ in range(7):
            counter.on_click({"element": "dec"})
        check("counter.clamped_to_minimum", doc.get_text("value") == "-50", text=doc.get_text("value"))
        classes = _attribute(doc, "value", "class") or ""
        check("counter.classes_from_batch", "negative" in classes and "at-limit" in classes, classes=classes)
        check("counter.history_entries", _count(doc, "#history li") == 8)
        counter.on_click({"element": "reset"})
        counter.set_count(3, "+3")
        check("counter.history_trimmed_to_8", _count(doc, "#history li") == example.HISTORY)
        check("counter.newest_first_and_escaped", doc.get_text("history").startswith("+3 -> 3"),
              text=doc.get_text("history")[:40])
        classes = _attribute(doc, "value", "class") or ""
        check("counter.classes_removed", "negative" not in classes and "at-limit" not in classes, classes=classes)
        counter.on_click({"element": "step"})          # a click on the select changes nothing
        check("counter.other_clicks_ignored", doc.get_text("value") == "3")
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- process viewer
def process_viewer(app):
    import process_viewer as example

    viewer = example.build(app)
    doc = viewer.document
    with Guard("processes"):
        total = _count(doc, "#rows tr")
        check("processes.rows_rendered", total >= 2, rows=total)
        check("processes.status_counts", doc.get_text("status").startswith(f"Showing {total} of "))
        check("processes.default_sort_memory", _attribute(doc, "col-MemoryMB", "aria-sort") == "descending")
        viewer.on_filter({"value": f" {os.getpid()} "})       # this backend's own process id
        check("processes.pid_filter_one_row", _count(doc, "#rows tr") == 1)
        viewer.on_filter({"value": ""})
        viewer.on_header({"element": "sort-Name"})
        check("processes.sort_name_ascending", _attribute(doc, "col-Name", "aria-sort") == "ascending"
              and _attribute(doc, "col-MemoryMB", "aria-sort") == "none")
        names = [p.name.lower() for p in viewer.visible()]
        check("processes.sorted_by_name", names == sorted(names))
        viewer.on_header({"element": "sort-Name"})
        check("processes.sort_toggles", _attribute(doc, "col-Name", "aria-sort") == "descending")
        viewer.snapshot = [example.Process("<b>evil</b> & co", 4242, 1.5, 0.25)]
        viewer.render()
        check("processes.names_escaped", _count(doc, "#rows b") == 0 and "<b>evil</b> & co" in doc.get_text("rows"))
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- keyboard shortcuts
def keyboard_shortcuts(app):
    import keyboard_shortcuts as example

    path = _scratch() / "snippet.txt"
    path.write_text("saved earlier", encoding="utf-8")
    editor = example.build(app, path)
    doc = editor.document

    def press(key, **modifiers):
        editor.on_key({"type": "keydown", "key": key, "ctrl": False, "shift": False, "alt": False, "meta": False,
                       **modifiers})
    with Guard("keys"):
        check("keys.loads_file", doc.get_value("editor") == "saved earlier")
        check("keys.chord_names", example.chord({"key": "U", "ctrl": True, "shift": True}) == "ctrl+shift+u")
        doc.set_value("editor", "ab")
        doc.set_control_selection("editor", 1, 1)
        press("Tab")
        check("keys.tab_indents_at_caret", doc.get_value("editor") == "a    b", value=doc.get_value("editor"))
        doc.set_control_selection("editor", 0, 1)
        press("U", ctrl=True, shift=True)
        check("keys.upper_case_selection", doc.get_value("editor") == "A    b")
        doc.set_value("editor", "\U0001F600ab")             # the emoji is two UTF-16 units
        doc.set_control_selection("editor", 2, 3)
        press("U", ctrl=True, shift=True)
        check("keys.utf16_offsets", doc.get_value("editor") == "\U0001F600Ab", value=doc.get_value("editor"))
        doc.set_control_selection("editor", 1 + 2, 3)
        press("U", ctrl=True, shift=True)
        check("keys.empty_selection_message", doc.get_text("status") == "Select some text first.")
        press("s", ctrl=True)
        check("keys.ctrl_s_saves", path.read_text(encoding="utf-8") == "\U0001F600Ab"
              and doc.get_text("status").startswith("Saved "))
        doc.set_value("editor", "")
        press("l", ctrl=True)
        check("keys.ctrl_l_timestamp", len(doc.get_value("editor")) == len("2026-01-01 00:00"),
              value=doc.get_value("editor"))
        press("F1")
        check("keys.f1_opens_help", doc.command("get_popover", element="help")["open"] is True)
        press("Escape")
        check("keys.escape_closes_help", doc.command("get_popover", element="help")["open"] is False)
        press("x", alt=True)                              # unknown chord: nothing happens
        check("keys.unknown_chord_ignored", doc.command("get_popover", element="help")["open"] is False)
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- diagnostics
def diagnostics(app):
    import zipfile

    import diagnostics as example

    output = _scratch()
    window = example.build(app, output)
    doc = window.document
    with Guard("diagnostics"):
        counters = window.refresh()
        check("diagnostics.no_callback_failures", counters["Callback failures"] == 0, counters=counters)
        check("diagnostics.feature_rows", _count(doc, "#features tr") == len(example.FEATURES))
        check("diagnostics.host_rows", _count(doc, "#host tr") == 8 and "linux" in doc.get_text("host")
              or os.name == "nt")
        if _headless(app):
            check("diagnostics.headless_reported", "HeadlessTrue" in doc.get_text("host"),
                  text=doc.get_text("host"))
            check("diagnostics.features_unavailable_headless", _count(doc, "#features td.no") == len(example.FEATURES))
        path = window.export()
        check("diagnostics.bundle_written", path is not None and path.is_file() and path.parent == output)
        with zipfile.ZipFile(path) as archive:
            names = sorted(archive.namelist())
        check("diagnostics.bundle_entries", names == ["manifest.json", "timeline.jsonl"], names=names)
        check("diagnostics.status_text", doc.get_text("bundle").startswith("Saved ")
              and doc.get_text("bundle").endswith("Attach it to a bug report."))
        window.output = path            # a file, not a folder: the export must fail visibly
        check("diagnostics.export_error_reported", window.export() is None
              and doc.get_text("bundle").startswith("Could not save the bundle"))
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- bulk rename
def bulk_rename(app):
    example = _load("bulk_rename/app.py", "bulk_rename_app")
    folder = _scratch()
    for name in ("IMG_0001.jpg", "IMG_0002.jpg", "img_0003.JPG", "notes.txt", "holiday_0001.jpg"):
        (folder / name).write_text(name, encoding="utf-8")
    tool = example.build(app, str(folder))
    doc = tool.document

    def rule(find, replace, *, regex=False, case=False):
        doc.set_value("find", find)
        doc.set_value("replace", replace)
        doc.set_checked("regex", regex)
        doc.set_checked("case", case)
        tool.update_preview()      # set_value does not fire input events
        return doc.get_text("summary")
    with Guard("rename"):
        check("rename.folder_listed", _count(doc, "#preview tr") == 5 and doc.get_text("summary") == "5 file(s), 0 to rename")
        check("rename.apply_disabled_without_plan", _attribute(doc, "apply", "disabled") is not None)
        summary = rule(r"^img_(\d+)", r"photo-\1", regex=True)
        check("rename.regex_preview", summary == "5 file(s), 3 to rename", summary=summary)
        check("rename.regex_groups", "photo-0003.JPG" in doc.get_text("preview"))
        check("rename.apply_enabled", _attribute(doc, "apply", "disabled") is None and doc.get_text("apply") == "Rename 3")
        summary = rule(r"^img_(\d+)", r"photo-\1", regex=True, case=True)
        check("rename.match_case", summary == "5 file(s), 1 to rename", summary=summary)
        rule("(", "", regex=True)
        check("rename.invalid_pattern", _count(doc, "#preview tr.error") == 5
              and doc.get_text("summary") == "5 file(s), 0 to rename, 5 skipped")
        rule("holiday", "IMG")
        check("rename.conflict_detected", _count(doc, "#preview tr.conflict") == 1)
        rule("notes", "a/b")
        check("rename.invalid_name", _count(doc, "#preview tr.invalid") == 1)
        rule("IMG_", "2026 $ \\1 ")
        check("rename.literal_replacement", "2026 $ \\1 0001.jpg" in doc.get_text("preview"))
        rule("IMG_", "2026 $ ")
        tool.ask_confirmation()
        check("rename.confirm_dialog_open", doc.command("get_dialog", element="confirm")["open"] is True
              and doc.get_text("confirm-text") == f"Rename 3 file(s) in {tool.folder}?")
        tool.confirm(True)
        check("rename.dialog_closed", doc.command("get_dialog", element="confirm")["open"] is False)
        names = sorted(p.name for p in folder.iterdir())
        check("rename.files_renamed", {"2026 $ 0001.jpg", "2026 $ 0002.jpg", "2026 $ 0003.JPG"} <= set(names), names=names)
        check("rename.summary_after", doc.get_text("summary") == "Renamed 3 file(s).")
        check("rename.undo_enabled", _attribute(doc, "undo", "disabled") is None)
        tool.undo()
        check("rename.undo_restores", doc.get_text("summary") == "Restored 3 file name(s)."
              and (folder / "img_0003.JPG").is_file() and (folder / "IMG_0001.jpg").is_file())
        tool.ask_confirmation()
        tool.confirm(False)
        check("rename.cancel_keeps_files", (folder / "IMG_0001.jpg").is_file())
        (folder / "2026 $ 0002.jpg").write_text("blocker", encoding="utf-8")   # appears after the preview
        tool.update_preview()
        tool.plan = [example.Row("IMG_0002.jpg", "2026 $ 0002.jpg", "rename")]
        tool.rename()
        check("rename.existing_target_not_overwritten", (folder / "IMG_0002.jpg").is_file()
              and (folder / "2026 $ 0002.jpg").read_text(encoding="utf-8") == "blocker"
              and doc.get_text("summary").startswith("Renamed 0 file(s). 1 failed"), text=doc.get_text("summary"))
        tool.open_folder(str(folder / "missing"))
        check("rename.missing_folder", doc.get_text("summary") == "That folder does not exist.")
        if _headless(app):
            check("rename.browse_disabled_headless", _attribute(doc, "browse", "disabled") is not None)
            tool.browse()
            check("rename.browse_fallback", _wait(lambda: doc.get_text("summary")
                                                   == "Native file dialogs are not available in this session."))
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- process dashboard
def process_dashboard(app):
    example = _load("process_dashboard/dashboard.py", "process_dashboard_app")
    dashboard = example.build(app, refresh_seconds=1)
    doc = dashboard.document
    with Guard("dashboard"):
        thread = dashboard.start()
        check("dashboard.first_refresh", _wait(lambda: dashboard.refreshes >= 1
                                               and doc.get_text("status").startswith("Updated "), 10))
        rows = _count(doc, "#rows tr")
        check("dashboard.rows", 0 < rows <= example.SHOWN, rows=rows)
        check("dashboard.summary", doc.get_text("summary").startswith(f"Showing {rows} of "))
        check("dashboard.keeps_refreshing", _wait(lambda: dashboard.refreshes >= 2, 5))
        dashboard.on_pause({"checked": True})
        time.sleep(0.2)
        paused_at = dashboard.refreshes
        check("dashboard.paused_status", doc.get_text("status") == "Paused")
        time.sleep(1.6)
        check("dashboard.pause_stops_refresh", dashboard.refreshes == paused_at, before=paused_at,
              after=dashboard.refreshes)
        with dashboard.lock:
            dashboard.rows = [example.list_processes.__globals__["Process"]("<i>x</i>", 7, 2.0, 1.0)]
        doc.set_value("filter", "<I>")
        dashboard.update_view()
        check("dashboard.filter_and_escape", _count(doc, "#rows tr") == 1 and _count(doc, "#rows i") == 0
              and "<i>x</i>" in doc.get_text("rows"))
        doc.set_value("filter", "")
        dashboard.copy()
        if _headless(app):
            check("dashboard.copy_fallback", doc.get_text("status") == "The clipboard is not available in this session")
        else:
            check("dashboard.copy", doc.get_text("status") == "Copied 1 rows")
        dashboard.on_pause({"checked": False})
        check("dashboard.resume_refreshes_at_once", _wait(lambda: dashboard.refreshes > paused_at, 0.9))
        dashboard.stop()
        thread.join(5)
        check("dashboard.thread_stops", not thread.is_alive())
    quit_when_ready(app, delay=0.2)


def tutorial_dashboard_step1(app):
    example = _load("process_dashboard/step1_snapshot.py", "process_dashboard_step1")
    doc = example.build(app)
    with Guard("dashboard_step1"):
        rows = _count(doc, "#rows tr")
        check("dashboard_step1.top_15", 0 < rows <= 15, rows=rows)
    quit_when_ready(app, delay=0.2)


def tutorial_dashboard_step2(app):
    example = _load("process_dashboard/step2_filter.py", "process_dashboard_step2")
    doc = example.build(app)
    with Guard("dashboard_step2"):
        check("dashboard_step2.summary", doc.get_text("summary").startswith("Showing "))
        doc.set_selected_values("sort", ["name"])
        doc.set_value("filter", "no-such-process-name")
        example.update_view(doc)
        check("dashboard_step2.filter_empty", _count(doc, "#rows tr") == 0
              and doc.get_text("summary").startswith("Showing 0 of "))
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- async counter
async def async_counter(app):
    import async_counter as example

    window = await asyncio.to_thread(app.open_html, example.HTML, title="Async counter check")
    counter = example.AsyncCounter(app, window)
    with Guard("async_counter"):
        await counter.increment({})
        await counter.increment({})
        text = await asyncio.to_thread(window.document.get_text, "count")
        check("async_counter.awaitable_updates", text == "2" and counter.count == 2, text=text)
    quit_when_ready(app, delay=0.2)
    await counter.adapter.run()
