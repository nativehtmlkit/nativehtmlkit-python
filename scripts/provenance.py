"""Deterministic source provenance shared by packaging and qualification scripts (stdlib only)."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {".git", "__pycache__", ".pytest_cache", "dist", "build", ".venv", "verification", ".ruff_cache"}
EXCLUDED_SUFFIXES = (".pyc", ".pyo", ".whl", ".egg-info")


def source_files(root: Path = ROOT) -> list[Path]:
    files = []
    # Sort by the POSIX relative path string: sorting Path objects is case-insensitive on
    # Windows, which changed the digest order and therefore the tree hash across platforms.
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root)
        if any(part in EXCLUDED_DIRS or part.endswith(".egg-info") for part in relative.parts):
            continue
        if not path.is_file() or path.name.endswith(EXCLUDED_SUFFIXES):
            continue
        if relative.parts[:3] == ("src", "nativehtmlkit", "_bin") and path.name != "README.md":
            continue  # staged hosts are artifacts, not source
        files.append(path)
    return files


def source_tree_sha256(root: Path = ROOT) -> str:
    """SHA-256 over (relative POSIX path, NUL, file SHA-256, LF) for every source file."""
    digest = hashlib.sha256()
    for path in source_files(root):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode() + b"\n")
    return digest.hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_state(root: Path = ROOT) -> dict:
    """Commit of the repository that owns ``root`` (None if not a Git checkout of its own)."""
    try:
        top = subprocess.run(["git", "-C", str(root), "rev-parse", "--show-toplevel"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        if not top or Path(top).resolve() != root.resolve():
            return {"commit": None, "note": "not an independent Git checkout"}
        commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True,
                                timeout=10).stdout.strip()
        dirty = bool(subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True,
                                    text=True, timeout=10).stdout.strip())
        return {"commit": commit or None, "dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        return {"commit": None, "note": "git unavailable"}


def sdk_version(root: Path = ROOT) -> str:
    import re
    text = (root / "src/nativehtmlkit/__init__.py").read_text(encoding="utf-8")
    return re.search(r'^__version__ = "([^"]+)"', text, re.M).group(1)


if __name__ == "__main__":
    print(json.dumps({"source_tree_sha256": source_tree_sha256(), "files": len(source_files()),
                      "git": git_state(), "sdk_version": sdk_version()}, indent=2))
