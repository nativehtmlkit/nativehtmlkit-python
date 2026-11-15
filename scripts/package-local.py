#!/usr/bin/env python3
"""Build local NativeHTMLKit Python distributions around EXACT prebuilt Core hosts.

Never compiles Rust, downloads a host, uploads, tags or publishes anything.

    python scripts/package-local.py --out dist/ \\
        --host linux-x64=/path/nativehtmlkit-host=SHA256 \\
        --host windows-x64=/path/nativehtmlkit-host.exe=SHA256 [--sdist] [--core-version 1.0.2]

For each --host: verify SHA-256 (fail closed), executable format and architecture,
stage a private copy of the source tree with only that host, build a
``py3-none-<platform>`` wheel, then re-open the wheel and verify the embedded host
digest and manifest. ``--sdist`` adds a host-less source distribution (building a
wheel from it requires staging a host again, or NATIVEHTMLKIT_DEV_SOURCE_ONLY=1 for
a pure development wheel). Writes ``SHA256SUMS`` and ``dist-manifest.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from provenance import ROOT, file_sha256, git_state, sdk_version, source_files, source_tree_sha256  # noqa: E402

PLATFORMS = {"linux-x64": ("nativehtmlkit-host", None),  # tag: manylinux_<glibc floor>_x86_64
             "windows-x64": ("nativehtmlkit-host.exe", "win_amd64")}
# Reproducible artifacts: fixed timestamps unless the caller pins SOURCE_DATE_EPOCH.
DEFAULT_EPOCH = 1794700800  # 2026-11-15T00:00:00Z


def expected_tag(platform: str, glibc: str | None) -> str:
    if platform == "linux-x64":
        if not glibc:
            raise PackagingError("cannot determine the Linux host's glibc floor")
        major, minor = glibc.split(".")
        return f"manylinux_{major}_{minor}_x86_64"
    return PLATFORMS[platform][1]
CONTRACT_SHA = json.loads((ROOT / "contracts/SOURCE.json").read_text())["sha256"]


class PackagingError(Exception):
    pass


def executable_platform(data: bytes) -> str:
    """Identify x86-64 ELF / PE32+ AMD64 images from their headers."""
    if data[:4] == b"\x7fELF":
        if data[4] != 2 or data[5] != 1 or struct.unpack_from("<H", data, 18)[0] != 62:
            raise PackagingError("ELF host is not little-endian x86-64")
        return "linux-x64"
    if data[:2] == b"MZ":
        offset = struct.unpack_from("<I", data, 0x3C)[0]
        if data[offset:offset + 4] != b"PE\0\0" or struct.unpack_from("<H", data, offset + 4)[0] != 0x8664:
            raise PackagingError("PE host is not AMD64")
        return "windows-x64"
    raise PackagingError("Host is neither an ELF nor a PE executable")


def glibc_floor(data: bytes) -> str | None:
    import re
    versions = {tuple(int(x) for x in m.split(b".")) for m in re.findall(rb"GLIBC_(\d+\.\d+)", data)}
    return ".".join(map(str, max(versions))) if versions else None


def normalize_wheel(path: Path, epoch: int) -> None:
    """Rewrite the zip with sorted entries, a fixed timestamp and normalised permissions."""
    import time as _time
    stamp = _time.gmtime(max(epoch, 315532800))[:6]
    with zipfile.ZipFile(path) as source:
        entries = [(info, source.read(info.filename)) for info in source.infolist()]
    temp = path.with_suffix(".tmp")
    with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as target:
        for info, data in sorted(entries, key=lambda item: item[0].filename):
            fresh = zipfile.ZipInfo(info.filename, date_time=stamp)
            executable = (info.external_attr >> 16) & 0o111
            fresh.external_attr = ((0o755 if executable else 0o644) | 0o100000) << 16
            fresh.compress_type = zipfile.ZIP_DEFLATED
            fresh.create_system = 3
            target.writestr(fresh, data)
    temp.replace(path)


def normalize_sdist(path: Path, epoch: int) -> None:
    """Rewrite the sdist tar.gz with sorted members, fixed mtime, root/root 0:0 ownership."""
    import gzip
    import io
    import tarfile
    with tarfile.open(path) as source:
        members = [(m, source.extractfile(m).read() if m.isfile() else None) for m in source.getmembers()]
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as target:
        for member, data in sorted(members, key=lambda item: item[0].name):
            member.mtime, member.uid, member.gid, member.uname, member.gname = epoch, 0, 0, "root", "root"
            member.pax_headers = {}
            if member.isdir():
                member.mode = 0o755
            elif member.isfile():
                member.mode = 0o755 if member.mode & 0o111 else 0o644
            target.addfile(member, io.BytesIO(data) if data is not None else None)
    with open(path, "wb") as handle, gzip.GzipFile(fileobj=handle, mode="wb", mtime=epoch, filename="") as zipped:
        zipped.write(raw.getvalue())


def parse_host(spec: str) -> tuple[str, Path, str]:
    try:
        platform, rest = spec.split("=", 1)
        path, expected = rest.rsplit("=", 1)
    except ValueError:
        raise PackagingError(f"--host must be PLATFORM=PATH=SHA256, got {spec!r}") from None
    if platform not in PLATFORMS:
        raise PackagingError(f"unknown platform {platform!r}; expected one of {sorted(PLATFORMS)}")
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected.lower()):
        raise PackagingError("expected SHA-256 must be 64 hex characters")
    return platform, Path(path).expanduser().resolve(), expected.lower()


def copy_core_notices(source: Path, destination: Path) -> list[str]:
    """The wheel redistributes Core: ship its licence and third-party notices (fail closed)."""
    required = [source / "LICENSE", source / "THIRD_PARTY_NOTICES.md"]
    missing = [p.name for p in required if not p.is_file()]
    if missing:
        raise PackagingError(f"Core notices {missing} not found in {source}; pass --core-notices")
    destination.mkdir(parents=True)
    copied = []
    for item in required + sorted((source / "licenses").glob("*")) if (source / "licenses").is_dir() else required:
        relative = item.relative_to(source)
        (destination / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, destination / relative)
        copied.append(relative.as_posix())
    matrix = source / "protocol/v1/method-matrix.json"
    if not matrix.is_file():
        raise PackagingError(f"{matrix} missing: pass the Core release directory with --core-notices so the "
                             "embedded host's protocol contract can be checked against contracts/SOURCE.json")
    if file_sha256(matrix) != CONTRACT_SHA:
        raise PackagingError("Core release method-matrix.json differs from contracts/SOURCE.json; "
                             "re-pin the contract and requalify before packaging")
    return copied


def stage_tree(destination: Path) -> None:
    for path in source_files():
        relative = path.relative_to(ROOT)
        if relative.parts[0] in ("tests", "scripts", "docs", "examples", "contracts"):
            continue  # not part of the distribution
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def build(staged: Path, kind: str, out: Path, *, env: dict) -> Path:
    before = set(out.iterdir())
    command = ["uv", "build", f"--{kind}", "--out-dir", str(out), str(staged)]
    if shutil.which("uv") is None:
        command = [sys.executable, "-m", "build", f"--{kind}", "--outdir", str(out), str(staged)]
    result = subprocess.run(command, cwd=staged, env=env, capture_output=True, text=True)
    if result.returncode:
        raise PackagingError(f"{' '.join(command[:3])} failed:\n{result.stdout[-2000:]}\n{result.stderr[-4000:]}")
    suffix = ".whl" if kind == "wheel" else ".tar.gz"
    created = sorted(p for p in set(out.iterdir()) - before if p.name.endswith(suffix))
    if len(created) != 1:
        raise PackagingError(f"expected one {kind} artifact, got {created}")
    return created[0]


def verify_wheel(wheel: Path, platform: str, host_sha: str, tag: str) -> dict:
    host_name = PLATFORMS[platform][0]
    if not wheel.name.endswith(f"-py3-none-{tag}.whl"):
        raise PackagingError(f"wheel {wheel.name} lacks platform tag {tag}")
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        hosts = [n for n in names if n.startswith("nativehtmlkit/_bin/nativehtmlkit-host")]
        if hosts != [f"nativehtmlkit/_bin/{host_name}"]:
            raise PackagingError(f"wheel must contain exactly one host {host_name}, found {hosts}")
        embedded = hashlib.sha256(archive.read(hosts[0])).hexdigest()
        manifest = json.loads(archive.read("nativehtmlkit/_bin/HOST-MANIFEST.json"))
        if manifest.get("platform") != platform or manifest.get("host_file") != host_name:
            raise PackagingError("wheel HOST-MANIFEST.json platform/host_file do not match the requested platform")
        if embedded != host_sha or manifest["host_sha256"] != host_sha:
            raise PackagingError("embedded host digest differs from the pinned SHA-256")
        for notice in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            if f"nativehtmlkit/_bin/core-licenses/{notice}" not in names:
                raise PackagingError(f"Core {notice} missing from wheel")
        if "nativehtmlkit/_skills/nativehtmlkit-python/SKILL.md" not in names:
            raise PackagingError("agent skill missing from wheel")
        if [n for n in names if "__pycache__" in n or n.endswith(".pyc")]:
            raise PackagingError("bytecode leaked into wheel")
        entry_points = archive.read(next(n for n in names if n.endswith(".dist-info/entry_points.txt"))).decode()
        if "\nnativehtmlkit =" in entry_points or entry_points.startswith("nativehtmlkit ="):
            raise PackagingError("wheel would install a competing `nativehtmlkit` executable")
        info = archive.getinfo(hosts[0])
        if platform == "linux-x64" and not (info.external_attr >> 16) & 0o111:
            raise PackagingError("Linux host lost its executable bit")
        licenses = [n for n in names if n.endswith(("LICENSE", "LICENSE.txt"))]
    return {"files": len(names), "license_files": licenses, "manifest": manifest}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", action="append", default=[], help="PLATFORM=PATH=SHA256 (repeatable)")
    parser.add_argument("--core-version", help="Core version string recorded in the manifest (informational)")
    parser.add_argument("--core-notices", type=Path,
                        help="directory with Core LICENSE + THIRD_PARTY_NOTICES.md (default: beside each host)")
    parser.add_argument("--sdist", action="store_true", help="also build a host-less source distribution")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.host and not args.sdist:
        parser.error("nothing to build: give --host and/or --sdist")
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        raise PackagingError(f"{out} must be new or empty; never overwrite staged releases")
    out.mkdir(parents=True, exist_ok=True)
    tree_sha = source_tree_sha256()
    version = sdk_version()
    artifacts = []
    env = dict(os.environ)
    env.pop("NATIVEHTMLKIT_DEV_SOURCE_ONLY", None)
    epoch = int(os.environ.get("SOURCE_DATE_EPOCH") or DEFAULT_EPOCH)
    env["SOURCE_DATE_EPOCH"] = str(epoch)
    hosts = [parse_host(spec) for spec in args.host]
    if len({p for p, _, _ in hosts}) != len(hosts):
        raise PackagingError("each platform may be given once")
    for platform, path, expected in hosts:
        if not path.is_file():
            raise PackagingError(f"host missing: {path}")
        data = path.read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise PackagingError(f"{platform} host SHA-256 mismatch: expected {expected}, file is {actual}")
        detected = executable_platform(data)
        if detected != platform:
            raise PackagingError(f"{path.name} is a {detected} executable, not {platform}")
        host_name, _tag = PLATFORMS[platform]
        with tempfile.TemporaryDirectory(prefix="nhk-py-stage-") as folder:
            staged = Path(folder) / "nativehtmlkit"
            stage_tree(staged)
            target = staged / "src/nativehtmlkit/_bin" / host_name
            target.write_bytes(data)
            target.chmod(0o755)
            notices = copy_core_notices(args.core_notices or path.parent, target.parent / "core-licenses")
            manifest = {"schema_version": 1, "sdk_version": version, "core_version": args.core_version,
                        "protocol_version": 1, "host_sha256": actual, "host_file": host_name,
                        "platform": platform, "source_tree_sha256": tree_sha,
                        "contract_method_matrix_sha256": CONTRACT_SHA,
                        "glibc_floor": glibc_floor(data) if platform == "linux-x64" else None,
                        "core_notices": notices,
                        "qualification": "UNQUALIFIED until the recorded host+SDK pair passes native gates"}
            (target.parent / "HOST-MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            wheel = build(staged, "wheel", out, env=env)
        tag = expected_tag(platform, glibc_floor(data) if platform == "linux-x64" else None)
        normalize_wheel(wheel, epoch)
        details = verify_wheel(wheel, platform, actual, tag)
        artifacts.append({"file": wheel.name, "kind": "wheel", "platform": platform, "sha256": file_sha256(wheel),
                          "size": wheel.stat().st_size, "host_sha256": actual, "verified": details})
    if args.sdist:
        with tempfile.TemporaryDirectory(prefix="nhk-py-sdist-") as folder:
            staged = Path(folder) / "nativehtmlkit"
            stage_tree(staged)
            sdist = build(staged, "sdist", out, env=env)
        normalize_sdist(sdist, epoch)
        import tarfile
        with tarfile.open(sdist) as archive:
            leaked = [n for n in archive.getnames() if "/_bin/nativehtmlkit-host" in n]
        if leaked:
            raise PackagingError(f"sdist must not contain a host: {leaked}")
        artifacts.append({"file": sdist.name, "kind": "sdist", "platform": "any", "sha256": file_sha256(sdist),
                          "size": sdist.stat().st_size, "host_sha256": None,
                          "note": "no host; build a wheel from it only after staging a pinned host"})
    sums = "".join(f"{a['sha256']}  {a['file']}\n" for a in artifacts)
    (out / "SHA256SUMS").write_text(sums, encoding="utf-8")
    (out / "dist-manifest.json").write_text(json.dumps({
        "schema_version": 1, "package": "nativehtmlkit", "sdk_version": version, "protocol_version": 1,
        "source_tree_sha256": tree_sha, "source_git": git_state(), "contract_method_matrix_sha256": CONTRACT_SHA,
        "core_version": args.core_version, "source_date_epoch": epoch,
        "built_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "artifacts": artifacts, "published": False}, indent=2) + "\n",
        encoding="utf-8")
    print(sums, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PackagingError as error:
        print(f"package-local: FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
