# Python SDK build, package and qualification

The `pyproject.toml` package uses setuptools. This project has a nonstandard but intentional **host-bundled wheel** flow: `setup.py` validates the staged host and emits a platform tag derived from that host's OS and glibc floor. A source-only development wheel (`NATIVEHTMLKIT_DEV_SOURCE_ONLY=1`) is not a substitute for a publishable platform wheel.

```bash
python -m pytest tests
python3 scripts/package-local.py --help
```

For a new registry version use the local packaging script with exact qualified Core release binaries, collect hash manifests, run native interactive qualification on Linux and Windows, inspect wheel contents, verify the README/skill were included, then use the repository's existing publish-only workflow after attaching a verified GitHub release. Do **not** edit a live version in place on PyPI.
