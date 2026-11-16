"""examples/catalog.toml: load it and enumerate every runnable file under examples/.

Shared by test_examples.py and test_example_behaviour.py. Pure stdlib (tomllib on 3.11+, a
minimal reader for this flat file on 3.10).
"""
from __future__ import annotations

import ast
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
CATALOG = EXAMPLES / "catalog.toml"
REQUIRED_KEYS = {"id", "title", "summary", "teaches", "file", "run", "language_specific"}

# Intermediate tutorial programs: started like examples, not catalogue entries.
TUTORIAL_STEPS = ("tutorial/step1_window.py", "tutorial/step2_add.py", "tutorial/step3_complete_delete.py",
                  "tutorial/step4_edit_keyboard.py", "process_dashboard/step1_snapshot.py",
                  "process_dashboard/step2_filter.py")
# Command-line arguments for programs that need them; "{log}" is a log file the test creates.
START_ARGS = {"log_viewer.py": ["{log}"]}
# Modules without a user interface, imported by examples.
HELPERS = ("process_dashboard/processes.py",)


def _parse_minimal(text: str) -> dict:
    entries: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "[[example]]":
            entries.append({})
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        value = {"true": True, "false": False}.get(value, value)
        entries[-1][key.strip()] = ast.literal_eval(value) if isinstance(value, str) else value
    return {"example": entries}


def load() -> list[dict]:
    text = CATALOG.read_text(encoding="utf-8")
    try:
        import tomllib
        data = tomllib.loads(text)
    except ModuleNotFoundError:  # Python 3.10
        data = _parse_minimal(text)
    return data["example"]


def entry_files() -> list[str]:
    return [entry["file"] for entry in load()]


def runnable_files() -> list[str]:
    """Every program the start-up test launches: catalogue entries plus tutorial steps."""
    return entry_files() + list(TUTORIAL_STEPS)


def python_files_on_disk() -> list[str]:
    return sorted(p.relative_to(EXAMPLES).as_posix() for p in EXAMPLES.rglob("*.py") if "__pycache__" not in p.parts)


def check_name(example_id: str) -> str:
    """The example_checks function that covers a catalogue id."""
    return example_id.replace("-", "_")
