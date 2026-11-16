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
        check("signup.invalid_events_listed", _wait(lambda: len(form.errors) == 6), errors=form.errors)
        check("signup.error_summary_rendered", _wait(lambda: _count(doc, "#errors li") == 6))
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

    viewer = example.build(app)
    doc = viewer.document
    with Guard("log"):
        viewer.append([("INFO", "started <b>service</b>"), ("ERROR", "disk & network down")])
        check("log.rows_appended", _count(doc, "#log .line") == 2)
        check("log.messages_escaped", _count(doc, "#log b") == 0 and "started <b>service</b>" in doc.get_text("log"))
        viewer.append([("DEBUG", f"line {i}") for i in range(example.MAX_ROWS + 50)])
        check("log.bounded_to_max_rows", _count(doc, "#log .line") == example.MAX_ROWS)
        check("log.oldest_trimmed", "started" not in doc.get_text("log") and doc.get_text("count") == f"{example.MAX_ROWS + 52} records")
        rows = doc.query_nodes("#log .DEBUG")["nodes"]
        hidden = doc.computed_style(["display"], doc.node(reference=rows[0]["node"]))["properties"]["display"]["value"]
        check("log.debug_hidden_at_info_level", hidden == "none", display=hidden)
        viewer.set_level("DEBUG")
        shown = doc.computed_style(["display"], doc.node(reference=rows[0]["node"]))["properties"]["display"]["value"]
        check("log.debug_shown_at_debug_level", shown == "block", display=shown)
        viewer.clear()
        thread = viewer.run_producer(example.simulated_records(), interval=0.1)
        check("log.producer_thread_appends", _wait(lambda: _count(doc, "#log .line") > 0, 5))
        viewer.paused.set()
        time.sleep(0.3)
        before = viewer.total
        time.sleep(0.4)
        check("log.pause_stops_appending", viewer.total == before, before=before, after=viewer.total)
        viewer.stopped.set()
        thread.join(2)
        check("log.producer_stops", not thread.is_alive())
    quit_when_ready(app, delay=0.2)


# --------------------------------------------------------------------------- settings dialog
def settings_dialog(app):
    import settings_dialog as example

    store = _scratch() / "settings.json"
    settings = example.build(app, store)
    doc = settings.document

    def background():
        return doc.computed_style(["background-color"], "body")["properties"]["background-color"]["value"]
    with Guard("settings"):
        light = background()
        settings.open()
        check("settings.dialog_open", doc.command("get_dialog", element="settings")["open"] is True)
        doc.set_value("display_name", "Grace <admin>")
        doc.set_selected_values("theme", ["dark"])
        doc.set_selected_values("font_size", ["large"])
        doc.set_checked("autosave", False)
        doc.request_submit("settings-form", submitter="save")
        check("settings.dialog_closed_after_save",
              _wait(lambda: doc.command("get_dialog", element="settings")["open"] is False))
        check("settings.return_value", doc.command("get_dialog", element="settings")["return_value"] == "saved")
        check("settings.status_from_close_event", _wait(lambda: doc.get_text("status") == "Settings saved."))
        check("settings.dark_scheme_applied", doc.environment()["color_scheme"] == "dark" and background() != light,
              light=light, dark=background())
        check("settings.greeting_plain_text", doc.get_text("greeting") == "Hello, Grace <admin>")
        saved = json.loads(store.read_text(encoding="utf-8"))
        check("settings.saved_json", saved == {"display_name": "Grace <admin>", "theme": "dark",
                                               "font_size": "large", "autosave": False}, saved=saved)
        settings.open()
        check("settings.form_prefilled", doc.get_value("display_name") == "Grace <admin>"
              and [o["value"] for o in doc.options("theme") if o["selected"]] == ["dark"])
        doc.close_dialog("settings", "cancel")
        check("settings.cancel_reported", _wait(lambda: doc.get_text("status") == "No changes made."))
        check("settings.help_popover_toggles", doc.toggle_popover("help") is True and doc.toggle_popover("help") is False)
        again = example.load_settings(store)
        check("settings.reload_from_disk", again["theme"] == "dark")
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
def window_manager(app):
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
def text_toolbox(app):
    import text_toolbox as example

    box = example.build(app)
    doc = box.document
    with Guard("toolbox"):
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
async def async_jobs(app):
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
def checksum(app):
    import checksum as example

    tool = example.build(app)
    doc = tool.document
    folder = _scratch()
    files = {"a.txt": b"alpha", "sub/b <x>.bin": bytes(range(256)) * 4000, "c.md": b""}
    for name, data in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(data)
    with Guard("checksum"):
        worker = tool.start(folder)
        check("checksum.worker_started", worker is not None)
        worker.join(30)
        expected = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
        check("checksum.hashes_correct", tool.results == expected)
        check("checksum.rows_rendered", _count(doc, "#results tr") == 3)
        check("checksum.names_escaped", "sub/b <x>.bin" in doc.get_text("results"))
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
