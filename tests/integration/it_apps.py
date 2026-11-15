"""Backend apps run by the REAL Core host via ``python -m nativehtmlkit run it_apps:<name>``.

Each app performs behaviour assertions against the live host and reports them with
``it_support.check``; the pytest driver (test_real_host.py) asserts on those records,
the launcher exit status and process cleanup. Works headless (``--headless``) and on
a real desktop.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from pathlib import Path

from it_support import Guard, check, emit, expect_raises, quit_when_ready

import nativehtmlkit
from nativehtmlkit import diagnostics
from nativehtmlkit.application import StaleDocumentError
from nativehtmlkit.client import DisconnectedError, ProtocolError, RpcError, encode_frame, write_all
from nativehtmlkit.errors import LocalRequestError, RpcTimeoutError

FORM = """<main>
<form id="f"><input id="name" name="name" value="a"><input id="agree" type="checkbox" name="agree">
<select id="sel" name="sel"><option value="x">X</option><option value="y">Y</option></select>
<button id="go" type="submit">Go</button></form>
<p id="status">init</p><ul id="list"><li>one</li><li>two</li></ul>
<img id="img" src="ui4me-bitmap://live" width="4" height="4"></main>"""
BIG_HTML = "<p>" + ("x" * 900_000) + "</p>"
# Credentials/role names the SDK must remove (UI4ME_TEST_MODE etc. are non-secret host flags).
WIRE = ("UI4ME_ENDPOINT", "UI4ME_TOKEN", "UI4ME_APP_ID", "UI4ME_PROTOCOL_VERSION", "UI4ME_DIRECT_START")


def _common_environment_checks(app):
    hello = app.rpc.hello
    check("hello.protocol_v1", hello.get("protocol_version") == 1, host_version=hello.get("host_version"))
    check("hello.app_id_present", bool(hello.get("app_id")))
    emit("info", name="host_version", value=hello.get("host_version"))
    check("env.wire_vars_scrubbed", not [k for k in os.environ if k in WIRE], present=[k for k in os.environ if k.startswith("UI4ME_")])
    child = subprocess.run([sys.executable, "-c",
                            "import os,json;print(json.dumps(sorted(k for k in os.environ if k in %r)))" % (WIRE,)],
                           capture_output=True, text=True, timeout=30)
    check("env.child_inherits_no_wire_vars", child.stdout.strip() == "[]", stdout=child.stdout.strip())
    expected = os.environ.get("NHK_IT_EXPECT_SESSION")
    if expected:
        check("session.flows_to_backend", diagnostics.SESSION_ID == expected, actual=diagnostics.SESSION_ID)
    check("session.exported_to_children", os.environ.get("NATIVEHTMLKIT_DIAGNOSTIC_SESSION_ID") == diagnostics.SESSION_ID)


def api_main(app):
    _common_environment_checks(app)
    with Guard("capabilities"):
        caps = app.capabilities()
        check("capabilities.is_object", isinstance(caps, dict) and "features" in caps)
        emit("info", name="capabilities", headless=caps.get("headless"), keys=sorted(caps))
    window = app.open_html(FORM, title="IT api", width=640, height=480)
    document = window.document
    with Guard("startup"):
        # Core 1.0.2 (NHK-CROSS-0002 fixed): a backend close of a NON-last window before
        # app.ready closes only that window, so open_html() cleanup failures are catchable.
        expect_raises("startup.open_html_failure_catchable", RpcError, app.open_html,
                      "x" * (1024 * 1024 + 10), title="IT too big", width=200, height=120)
        extra = app.open_html("<p>temporary</p>", title="IT early close", width=200, height=120)
        extra.request_close()
        deadline = time.monotonic() + 5
        while not extra.closed and time.monotonic() < deadline:
            time.sleep(0.05)
        check("startup.early_secondary_close_gets_closed_event", extra.closed)
        check("startup.app_still_running", window.state().get("window_id") == window.id)
    with Guard("document.basic"):
        document.set_text("status", "changed")
        check("document.set_get_text", document.get_text("status") == "changed")
        document.set_value("name", "Příliš 😀 ok")
        check("document.unicode_value_roundtrip", document.get_value("name") == "Příliš 😀 ok")
        document.set_checked("agree", True)
        check("document.checked", document.get_checked("agree") is True)
        document.set_selected_values("sel", ["y"])
        options = document.options("sel")
        check("document.select_options", [o.get("value") for o in options if o.get("selected")] == ["y"], options=options)
        document.set_attribute("status", "data-x", "1")
        document.add_class("status", "hot")
        queried = document.query("#list li")
        check("document.query", queried.get("matched_nodes") == 2 or queried.get("total") == 2, result=queried)
        document.batch([{"op": "set_text", "element": "status", "text": "batched"}])
        check("document.batch", document.get_text("status") == "batched")
    with Guard("forms"):
        data = document.form_data("f")
        entries = {e["name"]: e.get("value") for e in data["entries"]}
        check("forms.form_data", entries.get("name") == "Příliš 😀 ok" and entries.get("sel") == "y", entries=entries)
        got, thread_names = threading.Event(), []

        def on_submit(event):
            thread_names.append(threading.current_thread().name)
            # A callback may issue host RPCs (never on the transport reader thread).
            check("callback.can_call_rpc", document.get_text("status") == "batched")
            got.set()
        unsubscribe = document.on("submit", on_submit, element="f")
        result = document.request_submit("f")
        check("forms.request_submit_result", result.get("submitted") is True, result=result)
        check("forms.submit_event_delivered", got.wait(5))
        check("callback.not_on_reader_thread", thread_names and "receiver" not in thread_names[0]
              and "writer" not in thread_names[0], threads=thread_names)
        unsubscribe()
        got.clear()
        document.request_submit("f")
        check("subscription.disposed_sync", not got.wait(1.0))
    with Guard("nodes"):
        node = document.node("list")
        node.insert_html('<li id="three">three</li>')
        check("nodes.insert_html", document.query_nodes("#list li")["total"] == 3)
        listed = document.query_nodes("li")
        check("nodes.query_nodes", listed["total"] == 3 and len(listed["nodes"]) == 3)
        children = node.children()
        check("nodes.children", isinstance(children, dict))
        document.node(reference=listed["nodes"][0]["node"] if isinstance(listed["nodes"][0], dict) else listed["nodes"][0]).set_text("first")
        check("nodes.reference_set_text", document.query_nodes("#list li")["total"] == 3)
    with Guard("bitmap"):
        bitmap = document.create_bitmap("live", 4, 4)
        transport = bitmap.path
        presented = bitmap.present(bytes(range(64)))
        check("bitmap.present", isinstance(presented, dict), result=presented)
        check("bitmap.try_present", bitmap.try_present(bytes(64)) is not None)
        bitmap.close()
        check("bitmap.closed", bitmap._closed)
        # Leak check keyed to the path the HOST returned (its location is host-defined).
        time.sleep(0.3)
        check("bitmap.transport_file_released", not transport.exists(), transport_dir=transport.parent.name)
    with Guard("resources"):
        registered = document.register_resources("pack", {"a.txt": (b"hello", "text/plain")})
        check("resources.register", registered.get("name") == "pack")
        check("resources.stats", isinstance(document.resource_stats(), dict))
    with Guard("window"):
        window.set(title="IT api renamed")
        state = window.state()
        check("window.set_get", state.get("title") == "IT api renamed", title=state.get("title"))
        listed = app.rpc.call("window.list")
        check("window.list_contains", any((w.get("window_id") if isinstance(w, dict) else w) == window.id for w in listed))
    with Guard("lowlevel"):
        diag = app.rpc.call("host.diagnostics")
        # backend_pid is the process the host spawned; with a venv redirector python.exe on
        # Windows that is the launcher stub, not os.getpid().
        check("lowlevel.host_diagnostics", "logging" in diag and isinstance(diag.get("backend_pid"), int)
              and diag.get("pid") not in (None, os.getpid()), backend_pid=diag.get("backend_pid"))
        emit("info", name="backend_pid_is_self", value=diag.get("backend_pid") == os.getpid())
        emit("info", name="host_logging_counters", value=diag.get("logging"))
        error = expect_raises("lowlevel.unknown_method", RpcError, app.rpc.call, "no.such_method")
        check("lowlevel.unknown_method_code", getattr(error, "code", None) == -32601
              and getattr(error, "operation", None) == "no.such_method" and getattr(error, "request_id", None))
        error = expect_raises("lowlevel.unknown_member", RpcError, app.rpc.call, "window.get",
                              {"window_id": window.id, "bogus": 1})
        check("lowlevel.unknown_member_code", getattr(error, "code", None) == -32602)
    with Guard("dialogs"):
        caps = app.capabilities()
        if caps.get("headless"):
            error = expect_raises("dialogs.headless_unsupported", RpcError, window.open_files)
            check("dialogs.headless_code", getattr(error, "code", None) == -32001)
    with Guard("limits"):
        error = expect_raises("limits.host_rejects_oversize_html", RpcError, window.load_html, "x" * (1024 * 1024 + 10))
        check("limits.oversize_html_code", getattr(error, "code", None) == -32005)
        # The caller's own oversized request is a local error; nothing is sent (FR-PY-12).
        expect_raises("limits.frame_over_2mib_refused_locally", LocalRequestError, app.rpc.call,
                      "window.get", {"window_id": window.id, "pad": "y" * (2 * 1024 * 1024)})
        check("limits.session_alive_after_refusals", window.state().get("window_id") == window.id)
    with Guard("deadline"):
        # Deterministic: the timed request is queued behind several large loads the host
        # must process first (the host handles one connection's requests in order).
        backlog = [app.rpc.call_async("document.load", {"window_id": window.id, "html": BIG_HTML}) for _ in range(6)]
        # A zero deadline behind the backlog cannot be met (a reply that wins a race against a
        # longer deadline is correctly returned, PY-24; Windows timer granularity made 5 ms racy).
        error = expect_raises("deadline.timeout_error", RpcTimeoutError, app.rpc.call, "document.load",
                              {"window_id": window.id, "html": BIG_HTML}, timeout=0)
        concurrent.futures.wait(backlog, 30)
        check("deadline.outcome_unknown", getattr(error, "outcome_unknown", False) is True
              and getattr(error, "operation", None) == "document.load")
        time.sleep(0.5)
        check("deadline.session_usable_after", isinstance(app.rpc.call("window.list"), list))
    with Guard("stale"):
        # Reload: whether or not the timed-out load committed, the facade is replaced now.
        old = window.load_html(FORM)
        new = window.load_html("<p id='x'>replaced</p>")
        expect_raises("stale.local_rejection", StaleDocumentError, old.set_text, "status", "x")
        error = expect_raises("stale.host_rejects_old_document_id", RpcError, app.rpc.call, "document.command",
                              {"window_id": window.id, "document_id": old.id,
                               "command": {"op": "get_text", "element": "x"}})
        check("stale.host_code_closed", getattr(error, "code", None) == -32004)
        check("stale.new_document_works", new.get_text("x") == "replaced")
    closed = []
    app.on_window_event(lambda p: closed.append(p.get("type")))
    app.on_shutdown(lambda: emit("info", name="on_shutdown_ran", windows_closed=closed.count("closed")))
    def after_ready():
        # Core cancels startup when ANY window closes before app.ready (host/mod.rs), so
        # window churn is exercised only after readiness (see docs/bugs entry).
        with Guard("bitmap_budget"):
            # Core 1.0.2 limits: 64 MiB per document, host-wide 256 MiB -> BUSY (-32005).
            hosts, bitmaps, refusal = [], [], None
            try:
                for i in range(5):
                    extra = app.open_html(f"<img src='ui4me-bitmap://b{i}'>", title=f"IT budget {i}", width=200, height=120)
                    hosts.append(extra)
                    try:
                        bitmaps.append(extra.document.create_bitmap(f"b{i}", 4096, 2048, slots=2))  # 64 MiB
                    except RpcError as error:
                        refusal = error
                        break
                per_document = None
                try:
                    hosts[0].document.create_bitmap("second", 64, 64)
                except RpcError as error:
                    per_document = error
            finally:
                for bitmap in bitmaps:
                    bitmap.close()
                for extra in hosts:
                    extra.request_close()
                settle = time.monotonic() + 10  # let the closes finish before the next scenario
                while any(not extra.closed for extra in hosts) and time.monotonic() < settle:
                    time.sleep(0.05)
            check("bitmap.host_budget_refused_with_busy", len(bitmaps) == 4 and refusal is not None
                  and refusal.code == -32005 and refusal.operation == "bitmap.create" and not refusal.local,
                  created=len(bitmaps), code=getattr(refusal, "code", None))
            check("bitmap.document_budget_refused_with_busy", getattr(per_document, "code", None) == -32005)
            check("bitmap.budget_no_leaked_facades", all(w.document._bitmaps == [] for w in hosts))
        with Guard("rapid_open_close"):
            before = {window.id}  # only the main window is expected to remain after each scenario
            for i in range(15):
                extra = app.open_html(f"<p id='p'>{i}</p>", title=f"IT rapid {i}", width=200, height=120)
                extra.request_close()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                after = {w.get("window_id") for w in app.rpc.call("window.list")}
                if after == before and set(app._windows) == before:
                    break
                time.sleep(0.1)
            check("rapid.windows_released", after == before, remaining=len(after - before))
            check("rapid.sdk_bookkeeping", set(app._windows) == before, sdk=len(app._windows))
        with Guard("multi_window"):
            windows, seen, lock = [], {}, threading.Lock()
            for i in range(4):
                extra = app.open_html(f"<form id='f{i}'><button>b</button></form>", title=f"IT multi {i}", width=240, height=160)
                windows.append(extra)

                def handler(event, i=i):
                    with lock:
                        seen.setdefault(i, []).append(event["document_id"])
                extra.document.on("submit", handler)
            for i, extra in enumerate(windows):
                extra.document.request_submit(f"f{i}")
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and len(seen) < 4:
                time.sleep(0.05)
            check("multi.events_routed_per_document",
                  all(seen.get(i) == [w.document.id] for i, w in enumerate(windows)), seen=seen)
            for extra in windows:
                extra.request_close()
    emit("ready", scenario="api")
    quit_when_ready(app, delay=0.3, then=after_ready)


async def async_main(app):
    _common_environment_checks(app)
    window = await asyncio.to_thread(app.open_html, FORM, title="IT async", width=640, height=480)
    document = window.document
    adapter = app.async_adapter()
    rpc = adapter.rpc
    loop_thread = threading.current_thread()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        with Guard("async.concurrency"):
            ticks = 0

            async def ticker():
                nonlocal ticks
                while True:
                    ticks += 1
                    await asyncio.sleep(0.001)
            tick_task = asyncio.create_task(ticker())
            calls = [rpc.call("document.command", {"window_id": window.id, "document_id": document.id,
                                                   "command": {"op": "get_text", "element": "status"}}) for _ in range(60)]
            results = await asyncio.gather(*calls)
            tick_task.cancel()
            check("async.gather_60_rpcs", all(r == {"text": "init"} for r in results), sample=results[:1])
            check("async.loop_progress_during_rpcs", ticks > 0, ticks=ticks)
        with Guard("async.callback_awaits_rpc_while_other_pending"):
            order, done = [], asyncio.Event()
            progress = {"ticks": 0}

            async def on_submit(event):
                order.append(("start", event["n"] if "n" in event else len(order)))
                check("async.callback_on_loop_thread", threading.current_thread() is loop_thread)
                text = await rpc.call("document.command", {"window_id": window.id, "document_id": document.id,
                                                            "command": {"op": "get_value", "element": "name"}})
                mixed = await asyncio.to_thread(document.get_text, "status")  # sync API off-loop
                await asyncio.sleep(0.2)
                order.append(("end", text.get("value"), mixed))
                if sum(1 for o in order if o[0] == "end") == 2:
                    done.set()
            unsubscribe = adapter.on_document_event(document, "submit", on_submit)

            async def ticker2():
                while not done.is_set():
                    progress["ticks"] += 1
                    await asyncio.sleep(0.005)
            t2 = asyncio.create_task(ticker2())
            # Two host events: the second is queued while the first callback awaits RPCs.
            await rpc.call("document.command", {"window_id": window.id, "document_id": document.id,
                                                "command": {"op": "request_submit", "element": "f"}})
            await rpc.call("document.command", {"window_id": window.id, "document_id": document.id,
                                                "command": {"op": "request_submit", "element": "f"}})
            # Meanwhile a foreign thread uses the sync API on the same transport.
            sync_results = []
            worker = threading.Thread(target=lambda: sync_results.extend(document.get_text("status") for _ in range(20)))
            worker.start()
            await asyncio.wait_for(done.wait(), 10)
            await asyncio.to_thread(worker.join, 10)
            await t2
            kinds = [o[0] for o in order]
            check("async.ordered_fifo_callbacks", kinds == ["start", "end", "start", "end"], order=order)
            check("async.callback_rpc_results", all(o[1] == "a" and o[2] == "init" for o in order if o[0] == "end"))
            check("async.loop_progress_while_callback_awaits", progress["ticks"] > 10, ticks=progress["ticks"])
            check("async.sync_thread_mixing", sync_results == ["init"] * 20)
            unsubscribe()
            await rpc.call("document.command", {"window_id": window.id, "document_id": document.id,
                                                "command": {"op": "request_submit", "element": "f"}})
            await asyncio.sleep(0.8)
            check("async.subscription_disposed", len(order) == 4, order=order)
        with Guard("async.deadline"):
            backlog = [rpc.call("document.load", {"window_id": window.id, "html": BIG_HTML}, timeout=60)
                       for _ in range(6)]
            backlog_task = asyncio.ensure_future(asyncio.gather(*backlog, return_exceptions=True))
            await asyncio.sleep(0)
            try:
                await rpc.call("document.load", {"window_id": window.id, "html": BIG_HTML}, timeout=0)
                check("async.deadline_raises", False)
            except RpcTimeoutError as error:
                check("async.deadline_outcome_unknown", error.outcome_unknown and error.operation == "document.load")
            await backlog_task
            check("async.usable_after_deadline", isinstance(await rpc.call("window.list"), list))
        with Guard("async.cancellation"):
            task = asyncio.create_task(rpc.call("host.capabilities"))
            await asyncio.sleep(0)
            task.cancel()
            try:
                await task
                emit("note", name="async.cancel_raced_completion")
            except asyncio.CancelledError:
                check("async.cancel_propagates", True)
            check("async.usable_after_cancel", isinstance(await rpc.call("host.capabilities"), dict))
    sync_on_loop = [w for w in caught if "running asyncio event loop" in str(w.message)]
    check("async.no_blocking_call_on_loop", not sync_on_loop, count=len(sync_on_loop))
    with Guard("async.deterministic_shutdown"):
        emit("ready", scenario="async")
        quit_when_ready(app, delay=0.2)
        started = time.monotonic()
        await asyncio.wait_for(adapter.run(), 20)
        check("async.run_returned_after_shutdown", app.rpc.shutdown_requested.is_set(),
              seconds=round(time.monotonic() - started, 3))
        check("async.dispatcher_stopped", adapter.dispatcher._task.done())


def callbacks_main(app):
    """Slow and throwing callbacks, then quit: shutdown must stay bounded."""
    _common_environment_checks(app)
    window = app.open_html(FORM, title="IT callbacks", width=480, height=360)
    document = window.document
    state = {"slow_started": threading.Event()}

    def slow(_):
        state["slow_started"].set()
        time.sleep(4)

    def throwing(_):
        raise ValueError("intentional failure in callback")
    document.on("submit", throwing)
    document.on("submit", slow)
    started = time.monotonic()

    def go():
        document.request_submit("f")
        check("callbacks.slow_running_before_quit", state["slow_started"].wait(5))
        emit("info", name="quit_requested_at", seconds=round(time.monotonic() - started, 3))
    app.on_shutdown(lambda: emit("info", name="on_shutdown_ran", seconds=round(time.monotonic() - started, 3)))
    emit("ready", scenario="callbacks")
    quit_when_ready(app, then=go)


def kill_host_main(app):
    """Kill the host while requests are in flight (backend dies with it on Linux/Windows)."""
    window = app.open_html(FORM, title="IT kill", width=320, height=240)
    host_pid = app.rpc.call("host.diagnostics")["pid"]
    emit("info", name="host_pid", value=host_pid)

    def kill():
        futures = [app.rpc.call_async("document.command", {"window_id": window.id, "document_id": window.document.id,
                                                           "command": {"op": "get_text", "element": "status"}})
                   for _ in range(40)]
        emit("info", name="killing_host", pending=len(futures))
        os.kill(host_pid, signal.SIGKILL if hasattr(signal, "SIGKILL") else signal.SIGTERM)
        outcome = {"done": 0, "disconnected": 0, "other": 0}
        started = time.monotonic()
        for future in futures:
            try:
                future.result(10)
                outcome["done"] += 1
            except DisconnectedError:
                outcome["disconnected"] += 1
            except Exception:
                outcome["other"] += 1
        emit("info", name="kill_outcome", seconds=round(time.monotonic() - started, 3), **outcome)
    emit("ready", scenario="kill")
    threading.Thread(target=lambda: (time.sleep(0.5), kill()), daemon=True).start()


def malformed_main(app):
    """Send an invalid frame to the host; it must end the connection and the SDK must say why."""
    window = app.open_html(FORM, title="IT malformed", width=320, height=240)
    app.rpc.flush()

    def inject():
        pending = app.rpc.call_async("window.get", {"window_id": window.id})
        try:
            pending.result(5)
        except Exception:
            pass
        bad = b"{not json"
        write_all(app.rpc._stream, len(bad).to_bytes(4, "big") + bad)
        future = app.rpc.call_async("window.list")
        started = time.monotonic()
        try:
            future.result(10)
            check("malformed.connection_ended", False)
        except DisconnectedError as error:
            check("malformed.pending_failed_with_disconnect", True,
                  seconds=round(time.monotonic() - started, 3), cause=type(error.__cause__).__name__,
                  operation=error.operation)
        except Exception as error:
            check("malformed.pending_failed_with_disconnect", False, error=type(error).__name__)
    emit("ready", scenario="malformed")
    threading.Thread(target=lambda: (time.sleep(0.5), inject()), daemon=True).start()


SUBMIT_FORM = """<main><h1>Sign in</h1>
<form id="login-form"><label for="token-input">Token</label>
<input id="token-input" name="token" type="text" value="">
<button id="submit" type="submit">Submit</button></form>
<p id="status" role="status">Waiting</p></main>"""


def submit_main(app):
    """'Submit did nothing' diagnostic scenario (NHK_IT_SUBMIT_BUG=1 attaches the handler to a typo id)."""
    bug = os.environ.get("NHK_IT_SUBMIT_BUG") == "1"
    sentinel = os.environ.get("NHK_IT_SENTINEL", "")
    window = app.open_html(SUBMIT_FORM, title="IT submit", width=520, height=360)
    document = window.document
    submitted = threading.Event()

    def on_submit(_event):
        value = document.get_value("token-input")
        document.set_text("status", "Signed in" if value else "Empty token")
        submitted.set()
    document.on("submit", on_submit, element="login-form-typo" if bug else "login-form")

    def drive():
        document.set_value("token-input", sentinel)
        result = document.request_submit("login-form")
        emit("info", name="request_submit", result=result)
        handled = submitted.wait(3)
        status = document.get_text("status")
        check("submit.handler_ran" if not bug else "submit.bug_reproduced_handler_not_run",
              handled if not bug else not handled, page_status=status)
        # Privacy probes: the sentinel also travels through a URL and a file path.
        with Guard("submit.privacy_probes"):
            folder = Path(tempfile.mkdtemp(prefix="nhk-it-"))
            probe = folder / f"{sentinel}.html"
            probe.write_text("<p>probe</p>", encoding="utf-8")
            extra = app.open_file(probe, title="IT probe", width=200, height=120)
            # Only where the host refuses (-32001 headless): on a real desktop this would
            # really launch a URL handler on a shared session.
            if app.capabilities().get("headless"):
                try:
                    app.open_external(f"https://example.invalid/?token={sentinel}")
                except RpcError:
                    pass
            extra.request_close()
        zip_path = os.environ.get("NHK_IT_ZIP")
        if zip_path:
            nativehtmlkit.export_support_bundle(Path(zip_path), capture_environment=True)
            emit("info", name="support_zip_written")
    emit("ready", scenario="submit", bug=bug)
    quit_when_ready(app, delay=0.2, then=drive)


def overflow_main(app):
    """Bounded diagnostics: thousands of traced RPCs, losses disclosed in the bundle manifest."""
    window = app.open_html(FORM, title="IT overflow", width=320, height=240)
    futures = []
    for _ in range(25):
        futures = [app.rpc.call_async("window.get", {"window_id": window.id}) for _ in range(100)]
        concurrent.futures.wait(futures, 10)
    summary = diagnostics.recorder().summary()
    check("overflow.history_bounded", summary["records"] <= 256, summary=summary)
    check("overflow.eviction_disclosed", summary["history_evicted"] > 0, summary=summary)
    zip_path = os.environ.get("NHK_IT_ZIP")
    if zip_path:
        nativehtmlkit.export_support_bundle(Path(zip_path))
    emit("ready", scenario="overflow")
    quit_when_ready(app)
