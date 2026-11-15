"""Asyncio adapter sharing the same single Rust-host protocol transport.

No second connection and no competing event loop: ``AsyncRpcClient`` wraps the
transport's ``concurrent.futures.Future`` with ``asyncio.wrap_future`` (never
``.result()`` on the loop). ``EventDispatcher`` runs callbacks on the owning
loop in FIFO order; transport threads only enqueue.
"""
from __future__ import annotations

import asyncio
import contextvars
import inspect
from typing import Any, Callable
from .client import CAUSE, RpcClient
from .errors import RpcTimeoutError
from . import diagnostics


class AsyncRpcClient:
    """Awaitable RPC over an existing :class:`RpcClient`.

    ``timeout`` (seconds, default 15; ``None`` = no deadline) expiry raises
    :class:`RpcTimeoutError` with ``outcome_unknown=True`` after asking the host
    to cancel. Cancelling the awaiting task also requests host cancellation and
    re-raises ``CancelledError``. Neither is a rollback.
    """

    def __init__(self, rpc: RpcClient):
        self._rpc = rpc

    async def call(self, method: str, params: dict | None = None, *, timeout: float | None = 15.0) -> Any:
        future = self._rpc._submit(method, params)  # transport future: wrap_future only schedules on the loop
        request_id = getattr(future, "request_id", None)
        task = asyncio.wrap_future(future)
        try:
            if timeout is None:
                return await task
            return await asyncio.wait_for(task, timeout)
        except asyncio.TimeoutError as error:
            # wait_for already cancelled the wrapped future, which sent request.cancel.
            future.cancel()
            diagnostics.record("rpc.timeout", level="ERROR", method=method, request_id=request_id)
            raise RpcTimeoutError("RPC deadline exceeded; remote outcome may be unknown",
                                  operation=method, request_id=request_id) from error
        except asyncio.CancelledError:
            future.cancel()
            diagnostics.record("rpc.cancel_requested", method=method, request_id=request_id)
            raise


# Set while a dispatcher runs a callback. Tasks created from inside the callback (wait_for,
# create_task, gather, ...) copy the context, so stop() can tell "called from within a
# dispatched callback" (must not await the dispatcher) from an external caller (drains).
_DISPATCHING: contextvars.ContextVar = contextvars.ContextVar("nativehtmlkit_dispatching", default=None)


class _CallbackCancelled(Exception):
    """An async callback ended by cancellation; reported like any callback failure."""


class EventDispatcher:
    """Bounded FIFO dispatcher; callbacks execute on their asyncio owner loop.

    Transport callback threads only enqueue. Callback failures (including a
    callback raising ``CancelledError``) are reported and do not prevent later
    events. A full queue or a closed loop drops the event and increments
    ``dropped`` (recorded as ``callback.queue_overflow``). Slow callbacks
    intentionally impose ordering; use tasks for independent work.
    """
    def __init__(self, loop: asyncio.AbstractEventLoop | None = None, *, capacity: int = 128):
        self.loop = loop or asyncio.get_running_loop()
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=capacity)
        self._closed = False
        self._stop_after_current = False
        self._inner: asyncio.Future | None = None
        self.dropped = 0
        self._task = self.loop.create_task(self._run(), name="nativehtmlkit-event-dispatcher")

    def _drop(self, reason: str) -> None:
        self.dropped += 1
        diagnostics.record("callback.queue_overflow", level="WARN", dropped=self.dropped, reason=reason)

    def submit(self, callback: Callable[[Any], Any], event: Any, *, active: Callable[[], bool] | None = None) -> None:
        """Queue ``callback(event)``. ``active`` is re-checked on the loop just before running."""
        if self._closed:
            return
        cause = CAUSE.get()

        def put() -> None:
            if self._closed:
                return
            try:
                self.queue.put_nowait((callback, event, active, cause))
            except asyncio.QueueFull:
                self._drop("queue_full")
        try:
            self.loop.call_soon_threadsafe(put)
        except RuntimeError:  # the owning loop is closed
            self._drop("loop_closed")

    async def _run(self):
        while True:
            if self._stop_after_current and self.queue.empty():
                return
            item = await self.queue.get()
            try:
                if item is None:
                    return
                callback, event, active, cause = item
                if active is not None and not active():
                    continue  # subscription disposed after the event was queued
                token = CAUSE.set(cause)
                dispatching = _DISPATCHING.set(self)
                try:
                    diagnostics.record("callback.started", level="TRACE", event_seq=cause, owner="asyncio")
                    try:
                        result = callback(event)
                    except asyncio.CancelledError:
                        # A synchronous call cannot receive this task's cancellation (no await
                        # happened), so this CancelledError is the callback's own failure.
                        raise _CallbackCancelled() from None
                    if inspect.isawaitable(result):
                        # A separate task distinguishes "the callback raised
                        # CancelledError" (a callback failure) from "this
                        # dispatcher is being cancelled" (asyncio.wait raises).
                        inner = asyncio.ensure_future(result)
                        self._inner = inner
                        try:
                            await asyncio.wait({inner})
                        except asyncio.CancelledError:
                            inner.cancel()
                            raise
                        finally:
                            self._inner = None
                        if inner.cancelled():
                            raise _CallbackCancelled()
                        error = inner.exception()
                        if error is not None:
                            raise error
                    diagnostics.record("callback.completed", level="TRACE", event_seq=cause, owner="asyncio")
                except _CallbackCancelled as error:
                    self._report(error, cause)
                except Exception as error:
                    self._report(error, cause)
                finally:
                    _DISPATCHING.reset(dispatching)
                    CAUSE.reset(token)
            finally:
                self.queue.task_done()

    def _report(self, error: BaseException, cause) -> None:
        diagnostics.record("callback.failed", level="ERROR", exception_type=type(error).__name__,
                           event_seq=cause, owner="asyncio")
        self.loop.call_exception_handler({"message": "NativeHTMLKit callback failed", "exception": error})

    async def stop(self):
        """Run already queued callbacks, then end the dispatcher task.

        Called from within a dispatched callback (``await app.close()`` in a handler, also
        through ``wait_for``/``create_task``/``gather`` wrappers created there) it does not wait
        for the dispatcher, which is waiting for that very callback: it marks the dispatcher to
        finish after the queued callbacks and returns. External callers wait for the drain.
        """
        if self._task.done():
            self._closed = True
            return
        self._closed = True
        if _DISPATCHING.get() is self or self._inside():
            self._stop_after_current = True
            try:
                self.queue.put_nowait(None)
            except asyncio.QueueFull:
                pass  # _stop_after_current ends the loop once the queue is drained
            return
        await self.queue.put(None)
        await self._task

    def _inside(self) -> bool:
        current = asyncio.current_task()
        return current is not None and (current is self._task or current is self._inner)


class AsyncApplication:
    """Async facade for an existing Application and its protocol client."""
    def __init__(self, app, *, loop: asyncio.AbstractEventLoop | None = None):
        self.app = app
        self.rpc = AsyncRpcClient(app.rpc)
        self.dispatcher = EventDispatcher(loop)
        self._unsubscribers: list[Callable[[], None]] = []

    def on_document_event(self, document, event_type: str, callback: Callable,
                          *, element: str | None = None) -> Callable[[], None]:
        """Run ``callback(event)`` (plain or ``async``) on the owning loop.

        The returned function disposes the subscription: once it returns, no
        new invocation starts, including for events already queued.
        """
        state = {"active": True}

        def forward(event):
            self.dispatcher.submit(callback, event, active=lambda: state["active"])
        unsubscribe_native = document.on(event_type, forward, element=element)

        def unsubscribe() -> None:
            state["active"] = False
            if callable(unsubscribe_native):
                unsubscribe_native()
        self._unsubscribers.append(unsubscribe)
        return unsubscribe

    def _dispose(self) -> None:
        for cancel in self._unsubscribers:
            cancel()
        self._unsubscribers.clear()

    async def run(self) -> None:
        """Await orderly shutdown. Cancelling this coroutine closes the connection."""
        worker = asyncio.ensure_future(asyncio.to_thread(self.app.run))
        try:
            await asyncio.shield(worker)
        except asyncio.CancelledError:
            # app.run() polls the transport every 0.1 s; closing it ends the thread.
            await asyncio.to_thread(self.app.close)
            try:
                await worker
            except Exception:
                pass
            raise
        finally:
            self._dispose()
            await self.dispatcher.stop()

    async def close(self) -> None:
        self._dispose()
        await asyncio.to_thread(self.app.close)
        await self.dispatcher.stop()
