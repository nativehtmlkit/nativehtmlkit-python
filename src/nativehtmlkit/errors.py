"""Cross-SDK failure semantics.

``classification`` is the stable SDK category string (``NHK-...``) on EVERY error.
For backwards compatibility ``code`` equals ``classification`` on all errors except
:class:`nativehtmlkit.RpcError`, where ``code`` is the numeric v1 wire code (int).
Never parse human-readable messages.

Every error may carry ``operation`` (the RPC method), ``request_id`` (the SDK's
wire request ID) and ``session_id`` (the diagnostics correlation ID).
``outcome_unknown`` is True when the host may or may not have applied the
operation (deadline, disconnect): the SDK never claims a rollback.
"""
from __future__ import annotations

from typing import Any


class NativeHTMLKitError(Exception):
    code: str = "NHK-UNKNOWN"
    classification: str = "NHK-UNKNOWN"
    retryable: bool = False
    outcome_unknown: bool = False

    def __init__(self, message: str, *, operation: str | None = None,
                 request_id: str | None = None, data: Any = None):
        super().__init__(message)
        self.operation = operation
        self.request_id = request_id
        self.data = data
        try:
            from .diagnostics import SESSION_ID
        except Exception:  # pragma: no cover - diagnostics must never break error creation
            SESSION_ID = None
        self.session_id = SESSION_ID


class RpcTimeoutError(NativeHTMLKitError, TimeoutError):
    """The local deadline expired. Cancellation was requested; the remote outcome is unknown."""
    code = classification = "NHK-TRANSPORT-TIMEOUT"
    outcome_unknown = True


class HostDisconnectedError(NativeHTMLKitError, ConnectionError):
    """The connection ended. ``pending_failed`` counts requests failed by the same event."""
    code = classification = "NHK-HOST-DISCONNECTED"
    outcome_unknown = True

    def __init__(self, message: str, *, pending_failed: int = 0, **kwargs):
        super().__init__(message, **kwargs)
        self.pending_failed = pending_failed


class HostProtocolError(NativeHTMLKitError):
    """The HOST sent something that violates wire v1. Fatal for the session."""
    code = classification = "NHK-PROTOCOL-MALFORMED"


class LocalRequestError(NativeHTMLKitError, ValueError):
    """The caller's own request cannot be encoded (not JSON, non-string keys, > 2 MiB).
    Nothing was sent and the session continues."""
    code = classification = "NHK-REQUEST-INVALID"


class UnsupportedFeatureError(NativeHTMLKitError):
    code = classification = "NHK-FEATURE-UNSUPPORTED"


class StaleHandleError(NativeHTMLKitError):
    """A window, document or node handle that no longer refers to a live host object."""
    code = classification = "NHK-HANDLE-STALE"


class ApplicationShutdownError(StaleHandleError, RuntimeError):
    """The host already began shutdown (``app.shutdown``); no new windows can be created."""
    code = classification = "NHK-APP-SHUTDOWN"


class HostVerificationError(NativeHTMLKitError, FileNotFoundError):
    """The bundled host is missing its manifest or does not match its pinned SHA-256."""
    code = classification = "NHK-HOST-UNVERIFIED"
