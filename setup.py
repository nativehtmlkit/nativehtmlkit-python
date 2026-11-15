"""Platform wheel packaging of a prebuilt Core executable; never builds Rust.

Normal wheel builds require a host staged by ``scripts/package-local.py``
(``src/nativehtmlkit/_bin/<host>`` + ``HOST-MANIFEST.json`` whose SHA-256 matches).
The wheel platform tag comes from that manifest, not from the build machine, so a
Windows wheel can be assembled on Linux and vice versa.

``NATIVEHTMLKIT_DEV_SOURCE_ONLY=1`` builds a pure ``py3-none-any`` wheel WITHOUT a host
(development / sdist installs); such an install needs ``NATIVEHTMLKIT_HOST_BINARY``.
"""
from setuptools import Distribution, setup
from setuptools.command.build_py import build_py
from wheel.bdist_wheel import bdist_wheel
from pathlib import Path
import os
import shutil
import hashlib
import json

ROOT = Path(__file__).resolve().parent
BIN = ROOT / "src/nativehtmlkit/_bin"
WHEEL_TAGS = {"windows-x64": "win_amd64"}  # linux: manylinux_<glibc floor>_x86_64 from the manifest


def platform_tag(manifest: dict) -> str:
    """The wheel tag is derived from the embedded host: on Linux the host's glibc floor (e.g.
    2.39 -> manylinux_2_39_x86_64) so installers refuse systems where it cannot load."""
    if manifest.get("platform") == "linux-x64":
        floor = str(manifest.get("glibc_floor") or "")
        major, _, minor = floor.partition(".")
        if not (major.isdigit() and minor.isdigit()):
            raise RuntimeError("HOST-MANIFEST.json lacks the Linux host's glibc_floor; cannot tag the wheel")
        return f"manylinux_{major}_{minor}_x86_64"
    return WHEEL_TAGS[manifest["platform"]]
SOURCE_ONLY = os.environ.get("NATIVEHTMLKIT_DEV_SOURCE_ONLY") == "1"


def staged_manifest():
    manifest_file = BIN / "HOST-MANIFEST.json"
    if not manifest_file.is_file():
        raise RuntimeError(
            "This nativehtmlkit source tree contains no Core host. Install a platform wheel instead, or build a "
            "host-less development install with NATIVEHTMLKIT_DEV_SOURCE_ONLY=1 and point NATIVEHTMLKIT_HOST_BINARY "
            "at a host. (Release wheels are assembled from the repository with scripts/package-local.py.)")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    host = BIN / manifest.get("host_file", "")
    hosts = [p.name for p in BIN.iterdir() if p.is_file() and p.name.startswith("nativehtmlkit-host")]
    if not host.is_file() or hosts != [host.name]:
        raise RuntimeError(f"Exactly one staged host expected, found {hosts}")
    data = host.read_bytes()
    if manifest.get("host_sha256") != hashlib.sha256(data).hexdigest():
        raise RuntimeError("Staged Core binary hash does not match HOST-MANIFEST.json")
    expected_header = b"MZ" if manifest.get("platform") == "windows-x64" else b"\x7fELF"
    if not data.startswith(expected_header) or manifest.get("platform") not in ("linux-x64", "windows-x64"):
        raise RuntimeError("Staged Core host does not match the manifest platform")
    return manifest


class BundledHost(build_py):
    def run(self):
        if not SOURCE_ONLY:
            staged_manifest()
        super().run()
        built_bin = Path(self.build_lib) / "nativehtmlkit/_bin"
        if SOURCE_ONLY and built_bin.exists():
            for item in built_bin.iterdir():
                if item.name != "README.md":
                    shutil.rmtree(item) if item.is_dir() else item.unlink()
        skill = ROOT / "skills/nativehtmlkit-python"
        if not (skill / "SKILL.md").is_file():
            raise RuntimeError("NativeHTMLKit Python agent skill source missing")
        shutil.copytree(skill, Path(self.build_lib) / "nativehtmlkit/_skills/nativehtmlkit-python", dirs_exist_ok=True)


class PlatformWheel(bdist_wheel):
    def finalize_options(self):
        super().finalize_options()
        self.root_is_pure = SOURCE_ONLY

    def get_tag(self):
        if SOURCE_ONLY:
            return ("py3", "none", "any")
        return ("py3", "none", platform_tag(staged_manifest()))


class BinaryDistribution(Distribution):
    def has_ext_modules(self):
        return not SOURCE_ONLY


setup(distclass=BinaryDistribution, cmdclass={"build_py": BundledHost, "bdist_wheel": PlatformWheel})
