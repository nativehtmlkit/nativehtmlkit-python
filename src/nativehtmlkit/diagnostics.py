"""Local-first, bounded, privacy-safe diagnostics for NativeHTMLKit SDK clients.

Never captures JSON-RPC params/results, application text, credentials, raw paths or
user form values. Emission must never interfere with transport or GUI behavior.
"""
from __future__ import annotations

import atexit
from collections import deque
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import queue
import re
import threading
import time
import uuid
from typing import Any
import zipfile

LEVELS = {"off": 0, "normal": 1, "debug": 2, "trace": 3}
LEVEL_VALUES = {"ERROR": 1, "WARN": 1, "INFO": 2, "DEBUG": 2, "TRACE": 3}
_KEY_SECRET = re.compile(r"token|password|secret|credential|authorization|cookie|api.?key|\bkey\b|content|payload|body|html|path|url|text|value|filename|command_line|message|title|label|description", re.I)
_FIELD_SAFE = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,63}$")
# Same alphabet/length Core accepts for its `diagnostic_session_id` member, so one ID
# correlates the launcher, the host and the backend. Not a secret.
SESSION_PATTERN = re.compile(r"[A-Za-z0-9._:-]{1,128}")
_SESSION = (os.environ.get("NATIVEHTMLKIT_DIAGNOSTIC_SESSION_ID") or "").strip()
if not SESSION_PATTERN.fullmatch(_SESSION):
    _SESSION = "py-" + uuid.uuid4().hex
SESSION_ID = _SESSION
# Overwrite an invalid inherited value too: children (the host, the backend) must
# receive the ID this process actually records.
os.environ["NATIVEHTMLKIT_DIAGNOSTIC_SESSION_ID"] = SESSION_ID
_TOP_LEVEL = ("schema_version", "timestamp", "session_id", "component", "pid", "level", "event")


def _file_token(session: str) -> str:
    """Session IDs may contain ':' which Windows file names cannot."""
    return session.replace(":", "_")


def _safe(fields: dict[str, Any]) -> dict[str, Any]:
    from ._contract import DOCUMENT_OPS, METHODS
    result = {}
    for name, value in fields.items():
        if not _FIELD_SAFE.fullmatch(name):
            continue
        if name == "method" and value is not None:
            # Allow-list against the pinned contract: a caller-chosen string never reaches a record.
            result[name] = value if isinstance(value, str) and value in METHODS else "unknown-method"
        elif name == "op" and value is not None:
            result[name] = value if isinstance(value, str) and value in DOCUMENT_OPS else "unknown-op"
        elif _KEY_SECRET.search(name):
            result[name] = "[REDACTED]"
        elif isinstance(value, (bool, int, float)) and not isinstance(value, complex):
            result[name] = value if isinstance(value, (bool, int)) or (value == value and abs(value) != float('inf')) else "[INVALID]"
        elif isinstance(value, str):
            # Arbitrary strings can carry passwords/filenames; require short known identifiers.
            result[name] = value if len(value) <= 128 and re.fullmatch(r"[A-Za-z0-9_.:-]+", value) else "[REDACTED]"
        elif value is None:
            result[name] = None
        else:
            result[name] = "[REDACTED]"
    return result


class DiagnosticRecorder:
    """Bounded nonblocking records with in-memory last-N history.

    On an explicit debug/trace session, records are also written to a local JSONL
    file. Write errors and dropped records are counted, not raised into app code.
    """

    def __init__(self, *, level: str | None = None, directory: Path | None = None,
                 max_history: int = 256, max_pending: int = 1024,
                 max_file_bytes: int = 16 * 1024 * 1024):
        # NATIVEHTMLKIT_SDK_DIAGNOSTICS (set by the launcher) controls only this recorder; the
        # shared NATIVEHTMLKIT_DIAGNOSTICS also reaches the host (see _bootstrap._host_environment).
        self.level = (level or os.getenv("NATIVEHTMLKIT_SDK_DIAGNOSTICS")
                      or os.getenv("NATIVEHTMLKIT_DIAGNOSTICS", "normal")).lower()
        if self.level not in LEVELS:
            self.level = "normal"
        self.max_file_bytes = max_file_bytes
        self._history = deque(maxlen=max_history)
        self._pending = queue.Queue(maxsize=max_pending)
        self._lock = threading.Lock()
        self._lost = 0
        self._evicted = 0
        self._io_errors = 0
        self._closed = False
        self._worker = None
        self.path: Path | None = None
        if LEVELS[self.level] >= 2:
            parent = directory or diagnostics_directory()
            try:
                parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                self.path = parent / f"python-{_file_token(SESSION_ID)}-{os.getpid()}.jsonl"
                # File created with private permissions regardless of umask.
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(descriptor)
                self._worker = threading.Thread(target=self._write_loop, daemon=True, name="nhk-diag-writer")
                self._worker.start()
            except (OSError, ValueError):
                with self._lock:
                    self._io_errors += 1
                self.path = None

    def record(self, event: str, *, level: str = "DEBUG", **fields: Any) -> None:
        if LEVELS[self.level] < LEVEL_VALUES.get(level, 2):
            return
        # Event name is itself a fixed code, not an exception message.
        if not isinstance(event, str) or not _FIELD_SAFE.fullmatch(event):
            event = "diagnostics.invalid_event_name"
        item = {
            "schema_version": 1, "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": SESSION_ID, "component": "python-sdk",
            "pid": os.getpid(), "level": level, "event": event,
            "context": _safe(fields),
        }
        with self._lock:
            if len(self._history) == self._history.maxlen:
                self._evicted += 1
            self._history.append(item)
        if self._worker and self._closed:
            with self._lock:
                self._lost += 1  # writer already stopped: kept in memory only
        elif self._worker:
            try:
                self._pending.put_nowait(item)
            except queue.Full:
                with self._lock:
                    self._lost += 1

    def _write_loop(self) -> None:
        written = 0
        while True:
            item = self._pending.get()
            try:
                if item is None:
                    return
                line = (json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
                if written + len(line) <= self.max_file_bytes and self.path:
                    with self.path.open("ab") as handle:
                        handle.write(line)
                    written += len(line)
                else:
                    with self._lock:
                        self._lost += 1
            except OSError:
                with self._lock:
                    self._io_errors += 1
            finally:
                self._pending.task_done()

    def summary(self) -> dict[str, Any]:
        with self._lock:
            return {"schema_version": 1, "session_id": SESSION_ID, "level": self.level,
                    "records": len(self._history), "dropped": self._lost,
                    "history_evicted": self._evicted, "record_failures": _record_failures,
                    "io_errors": self._io_errors, "file": self.path.name if self.path else None}

    def history(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history)

    def close(self, *, timeout: float = 1.0) -> None:
        if self._closed:
            return
        self._closed = True
        if self._worker:
            # Bounded: diagnostics must not hold up exit, but whatever is still
            # queued when the deadline passes is counted as lost, never silently gone.
            try:
                self._pending.put(None, timeout=timeout)
                self._worker.join(timeout=timeout)
            except queue.Full:
                pass
            if self._worker.is_alive():
                with self._lock:
                    self._lost += max(self._pending.qsize() - 1, 0)


_recorder: DiagnosticRecorder | None = None
_recorder_lock = threading.Lock()


def recorder() -> DiagnosticRecorder:
    global _recorder
    with _recorder_lock:
        if _recorder is None:
            _recorder = DiagnosticRecorder()
        return _recorder


_record_failures = 0


def record(event: str, *, level: str = "DEBUG", **fields: Any) -> None:
    """Never raises into the caller; a failure is counted (``record_failures`` in summaries)."""
    global _record_failures
    try:
        recorder().record(event, level=level, **fields)
    except Exception:
        _record_failures += 1


def diagnostics_directory() -> Path:
    """``NATIVEHTMLKIT_DIAGNOSTICS_DIR``, else a private per-user state directory."""
    override = os.getenv("NATIVEHTMLKIT_DIAGNOSTICS_DIR")
    if override:
        return Path(override)
    if os.name == "nt" and os.getenv("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "NativeHTMLKit" / "diagnostics"
    return Path.home() / ".local/state/nativehtmlkit/diagnostics"


def _resanitize(raw: Any) -> dict[str, Any] | None:
    """Accept only well-formed SDK records; re-apply redaction to their context.

    A JSONL file on disk is not trusted to be sanitized (it may be stale, edited or
    produced by another version), so every exported record is filtered again.
    """
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return None
    event, session = raw.get("event"), raw.get("session_id")
    if not isinstance(event, str) or not _FIELD_SAFE.fullmatch(event):
        return None
    if not isinstance(session, str) or not SESSION_PATTERN.fullmatch(session):
        return None
    item = {key: raw.get(key) for key in _TOP_LEVEL}
    if not isinstance(item["pid"], int) or item["level"] not in LEVEL_VALUES:
        return None
    if not isinstance(item["timestamp"], str) or not re.fullmatch(r"[0-9T:.+-]{10,40}", item["timestamp"]):
        return None
    if item["component"] != "python-sdk":
        return None
    context = raw.get("context")
    item["context"] = _safe(context) if isinstance(context, dict) else {}
    return item


MAX_COLLECT_BYTES = 64 * 1024 * 1024


def latest_session(directory: Path | None = None) -> str | None:
    """Session ID of the most recently written SDK diagnostics file, if any."""
    folder = directory or diagnostics_directory()
    try:
        files = sorted(folder.glob("python-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    for file in files:
        try:
            with file.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    try:
                        record = _resanitize(json.loads(line))
                    except ValueError:
                        continue
                    if record:
                        return record["session_id"]
        except OSError:
            continue
    return None


def _collect(session: str, directory: Path) -> tuple[list[dict[str, Any]], int, int, int]:
    records, files, invalid, read = [], 0, 0, 0
    try:
        candidates = sorted(directory.glob("python-*.jsonl"))
    except OSError:
        return records, files, invalid, read
    for file in candidates:
        if file.is_symlink() or not file.is_file():
            continue
        matched = False
        try:
            with file.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    read += len(line)
                    if read > MAX_COLLECT_BYTES:
                        break
                    try:
                        record = _resanitize(json.loads(line))
                    except ValueError:
                        record = None
                    if record is None:
                        if line.strip():
                            invalid += 1
                        continue
                    if record["session_id"] == session:
                        matched = True
                        records.append(record)
        except OSError:
            continue
        files += matched
    records.sort(key=lambda r: r["timestamp"])
    return records, files, invalid, read


def export_bundle(path: Path, *, capture_environment: bool = False, session: str | None = None,
                  directory: Path | None = None, overwrite: bool = False) -> Path:
    """Create a local support ZIP for one diagnostics session. Explicit call only.

    Contents: ``manifest.json`` (counts, losses, versions) and ``timeline.jsonl``
    (re-sanitized SDK records of ``session``; default: this process's session).
    Records come from the session's JSONL files (debug/trace) or, when this
    process wrote none, from its in-memory history. Never included: RPC
    params/results, form values, tokens, environment variables, raw host stderr,
    screenshots or dumps.
    """
    import platform
    import sys
    r = recorder()
    if r._worker:
        # Explicit user-triggered operation: wait (bounded) for queued records to reach disk.
        flush_deadline = time.monotonic() + 10
        while (r._pending.unfinished_tasks and r._worker.is_alive()
               and time.monotonic() < flush_deadline):
            time.sleep(0.01)
    session = session or SESSION_ID
    if not SESSION_PATTERN.fullmatch(session):
        raise ValueError("Invalid diagnostics session ID")
    folder = directory or diagnostics_directory()
    records, files, invalid, read = _collect(session, folder)
    source = "files"
    if not records and session == SESSION_ID:
        records = [x for x in (_resanitize(item) for item in r.history()) if x]
        source = "memory"
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    info: dict[str, Any] = {"schema_version": 1, "session_id": session, "source": source,
                            "records": len(records), "collected_files": files, "invalid_lines": invalid,
                            "truncated": read > MAX_COLLECT_BYTES,
                            "exporter": r.summary() if session == SESSION_ID else None,
                            "diagnostics_sanitized": True,
                            "excluded": ["rpc_payloads", "form_values", "credentials", "environment",
                                         "host_stderr", "screenshots"]}
    try:
        from . import __version__
        info["sdk_version"] = __version__
    except ImportError:  # pragma: no cover
        pass
    if capture_environment:
        info["environment"] = {"os": platform.system(), "arch": platform.machine(),
                                "python": sys.version.split()[0]}
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} exists; pass overwrite=True (CLI: --force) to replace it")
    # Private (0600), unpredictable, exclusively created temporary file in the target directory.
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle, zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", json.dumps(info, sort_keys=True, indent=2))
            archive.writestr("timeline.jsonl", "".join(json.dumps(x, sort_keys=True) + "\n" for x in records))
        if overwrite:
            os.replace(temp, path)
        else:
            try:
                os.link(temp, path)  # atomic: fails if the target appeared meanwhile
            except FileExistsError:
                raise
            except OSError:
                if path.exists():
                    raise FileExistsError(f"{path} exists") from None
                os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()
    return path


@atexit.register
def _flush() -> None:
    if _recorder is not None:
        _recorder.close()
