"""Locate the installed NativeHTMLKit native host and forward its command-line API."""
from __future__ import annotations
import importlib.resources
import os
from pathlib import Path
import subprocess
import sys


HOST_NAME = "nativehtmlkit-host.exe" if os.name == "nt" else "nativehtmlkit-host"


ALLOW_PATH = "NATIVEHTMLKIT_ALLOW_PATH_HOST"


def _search_path() -> Path | None:
    """Explicit-opt-in PATH lookup: only absolute PATH entries, never the current directory
    (``shutil.which`` searches the cwd first on Windows) and never a relative result."""
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry or not os.path.isabs(entry):
            continue
        candidate = Path(entry) / HOST_NAME
        if candidate.is_file() and (os.name == "nt" or os.access(candidate, os.X_OK)):
            return candidate.resolve()
    return None


def _resolve() -> tuple[Path, str]:
    """(path, source): source is ``environment``, ``bundled`` or ``path``."""
    override = os.environ.get("NATIVEHTMLKIT_HOST_BINARY") or os.environ.get("UI4ME_HOST_BINARY")
    if override:
        binary = Path(override).expanduser().resolve()
        if not binary.is_file():
            raise FileNotFoundError(f"NATIVEHTMLKIT_HOST_BINARY does not exist: {binary}")
        return binary, "environment"
    binary = bundled_host_path()
    if binary.is_file():
        return binary, "bundled"
    if os.environ.get(ALLOW_PATH) == "1":
        found = _search_path()
        if found:
            return found, "path"
    raise FileNotFoundError(
        "NativeHTMLKit native host is missing. Install the platform wheel or set NATIVEHTMLKIT_HOST_BINARY "
        f"(an unpinned host on PATH is used only with {ALLOW_PATH}=1)."
    )


def bundled_host_path() -> Path:
    return Path(os.fspath(importlib.resources.files("nativehtmlkit").joinpath("_bin", HOST_NAME)))


def _verify_bundled(binary: Path) -> None:
    """The wheel's host must match the SHA-256 pinned in its HOST-MANIFEST.json."""
    import json
    from .errors import HostVerificationError
    manifest_file = binary.with_name("HOST-MANIFEST.json")
    try:
        manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HostVerificationError(f"Bundled host has no readable {manifest_file.name}; refusing to run it") from None
    expected = manifest.get("host_sha256") if isinstance(manifest, dict) else None
    if not isinstance(expected, str) or _sha256(binary) != expected.lower():
        raise HostVerificationError("Bundled host does not match the SHA-256 pinned in HOST-MANIFEST.json; "
                                    "refusing to run it (reinstall the wheel)")


def host_binary() -> Path:
    """The host to launch, verified where a pin exists.

    1. ``NATIVEHTMLKIT_HOST_BINARY`` (explicit development override, not verified);
    2. the wheel's bundled host, verified against ``HOST-MANIFEST.json`` on every call
       (:class:`~nativehtmlkit.errors.HostVerificationError` on mismatch/missing manifest);
    3. only with ``NATIVEHTMLKIT_ALLOW_PATH_HOST=1``: an absolute PATH match (unpinned; warned).
    """
    binary, source = _resolve()
    if source == "bundled":
        _verify_bundled(binary)
    elif source == "path":
        from . import diagnostics
        diagnostics.record("host.unpinned_path_fallback", level="WARN")
        print(f"nativehtmlkit: WARNING: using an unpinned host from PATH ({binary}); "
              f"it is not verified against any SHA-256", file=sys.stderr, flush=True)
    return binary


def _sha256(path: Path) -> str:
    import hashlib
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def host_info() -> dict:
    """Provenance of the host this SDK would launch (no process is started)."""
    import json
    info: dict = {"source": None, "path": None, "sha256": None, "manifest": None, "manifest_match": None}
    manifest_file = bundled_host_path().with_name("HOST-MANIFEST.json")
    if manifest_file.is_file():
        try:
            manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
            info["manifest"] = manifest if isinstance(manifest, dict) else {"error": "invalid"}
        except (OSError, ValueError):
            info["manifest"] = {"error": "unreadable"}
    try:
        binary, source = _resolve()
    except FileNotFoundError as error:
        info["error"] = str(error)
        return info
    info.update(source=source, path=str(binary), sha256=_sha256(binary))
    manifest = info["manifest"] or {}
    if "error" in manifest:
        info["manifest_match"] = False
    elif manifest.get("host_sha256"):
        info["manifest_match"] = manifest["host_sha256"] == info["sha256"]
    return info


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("Usage: nativehtmlkit-python-host [run --app APP.toml | doctor | render ... | --version]", file=sys.stderr)
        return 2
    try:
        binary = host_binary()
    except (OSError, FileNotFoundError) as error:
        print(str(error), file=sys.stderr)
        return 1
    from ._bootstrap import _host_environment
    env = _host_environment(dict(os.environ))  # same diagnostics mapping as every launch path
    if os.name == "posix":
        # Replace this Python wrapper with the native host so signals from a
        # process manager (SIGTERM, SIGHUP) reach the host itself instead of
        # orphaning it, and the host's exit status is returned unchanged.
        sys.stdout.flush()
        sys.stderr.flush()
        os.execve(str(binary), [str(binary), *args], env)
    return subprocess.call([str(binary), *args], env=env)


if __name__ == "__main__":
    raise SystemExit(main())
