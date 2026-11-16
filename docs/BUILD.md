# Python SDK build, package and qualification

The `pyproject.toml` package uses setuptools. This project has a nonstandard but intentional **host-bundled wheel** flow: `setup.py` validates the staged host and emits a platform tag derived from that host's OS and glibc floor. A source-only development wheel (`NATIVEHTMLKIT_DEV_SOURCE_ONLY=1`) is not a substitute for a publishable platform wheel.

```bash
bash scripts/test-local.sh                       # unit and fake-host suite (scripts/test-local.ps1 on Windows)
NATIVEHTMLKIT_HOST_BINARY=/path/to/nativehtmlkit-host python -m pytest tests/integration   # real host, headless
python3 scripts/package-local.py --help
```

`tests/integration/test_examples.py` starts every program in `examples/` and `examples/tutorial/`
until it is ready; `tests/integration/test_example_behaviour.py` drives each example's `build(...)`
function inside the host and reads the DOM back (`example_checks.py`). Set `NHK_IT_DESKTOP=1` to
run the same scenarios with real windows on the current desktop, or
`NATIVEHTMLKIT_TEST_INSTALLED=1` to test an installed wheel with its bundled host.

For a new registry version use the local packaging script with exact qualified Core release binaries, collect hash manifests, run native interactive qualification on Linux and Windows, inspect wheel contents, verify the README/skill were included, then use the repository's existing publish-only workflow after attaching a verified GitHub release. Do **not** edit a live version in place on PyPI.
