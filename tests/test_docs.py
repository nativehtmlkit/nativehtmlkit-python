"""Structure and consistency of the documentation tree (no host needed).

- every page starts with one ``# Title`` line and links only to pages that exist; links that
  leave docs/ are absolute GitHub URLs (the public site imports docs/ on its own)
- the canonical guides and tutorials exist, and the guide index lists the guides in order
- examples/catalog.toml names existing guides, and examples/README.md lists every entry
- tutorial excerpts are copied verbatim from the example files they name
- every Python block of the guides, getting started and new tutorials parses
"""
from __future__ import annotations

import ast
import re
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
PAGES = sorted(DOCS.rglob("*.md"))
sys.path.insert(0, str(ROOT / "tests" / "integration"))
import example_catalog  # noqa: E402

GUIDES = ["lifecycle", "events-and-callbacks", "updating-the-page", "forms-and-validation", "windows",
          "file-dialogs", "dialogs-and-popovers", "clipboard-and-desktop", "keyboard-and-focus",
          "styling-and-layout", "live-bitmaps", "background-work", "diagnostics-and-troubleshooting",
          "packaging-and-distribution", "project-scaffolding", "security"]
EXTRA_GUIDES = ["asyncio"]
TUTORIALS = ["todo-app", "bulk-rename", "process-dashboard"]
LINK = re.compile(r"\]\(([^)\s]+)\)")
BLOCK = re.compile(r'```python(?: title="([^"]*)")?\n(.*?)```', re.S)


def _ids(paths):
    return [p.relative_to(DOCS).as_posix() for p in paths]


@pytest.mark.parametrize("page", PAGES, ids=_ids(PAGES))
def test_page_has_one_title_and_valid_links(page: Path):
    text = page.read_text(encoding="utf-8")
    assert text.startswith("# "), "a page starts with a single '# Title' line"
    body = re.sub(r"```.*?```", "", text, flags=re.S)
    assert len(re.findall(r"^# ", body, re.M)) == 1, "exactly one top-level heading"
    for target in LINK.findall(body):
        if re.match(r"[a-z]+:", target) or target.startswith("#"):
            continue
        path = (page.parent / target.partition("#")[0]).resolve()
        assert path.is_relative_to(DOCS), f"{target}: link outside docs/ must be an absolute URL"
        assert path.exists(), f"broken link {target}"


# Reference pages show signatures and the todo tutorial shows diff-like fragments; every other
# Python block is complete code (possibly a method body, which is dedented first).
CODE_PAGES = [p for p in PAGES if p.parent.name != "reference" and p.name != "todo-app.md"]


@pytest.mark.parametrize("page", CODE_PAGES, ids=_ids(CODE_PAGES))
def test_python_blocks_parse(page: Path):
    for title, code in BLOCK.findall(page.read_text(encoding="utf-8")):
        try:
            ast.parse(textwrap.dedent(code))
        except SyntaxError as error:
            pytest.fail(f"{title or 'python block'}: {error}\n{code[:400]}")


def test_public_docs_have_no_private_details():
    pattern = re.compile(r"linuxDEV|winDEV|pvez|pvey|/home/toor|scratchpad|agent-workspaces", re.I)
    scripts = [p for folder in ("tests", "scripts") for p in sorted((ROOT / folder).rglob("*"))
               if p.suffix in {".py", ".sh", ".ps1", ".md", ".toml", ".json", ".txt"}
               and "__pycache__" not in p.parts and p != Path(__file__).resolve()]
    for page in PAGES + [ROOT / "README.md", ROOT / "examples" / "README.md"] + scripts:
        assert not pattern.search(page.read_text(encoding="utf-8")), page


def test_canonical_guides_and_tutorials_exist():
    for name in GUIDES + EXTRA_GUIDES:
        assert (DOCS / "guides" / f"{name}.md").is_file(), name
    for name in TUTORIALS:
        assert (DOCS / "tutorials" / f"{name}.md").is_file(), name
    assert (DOCS / "getting-started.md").is_file()
    index = (DOCS / "guides" / "README.md").read_text(encoding="utf-8")
    listed = re.findall(r"\]\(([a-z0-9-]+)\.md\)", index)
    assert [g for g in listed if g in GUIDES] == GUIDES, listed
    assert set(listed) == set(GUIDES + EXTRA_GUIDES), listed


def test_catalog_guides_and_example_index():
    readme = (ROOT / "examples" / "README.md").read_text(encoding="utf-8")
    for entry in example_catalog.load():
        if "guide" in entry:
            assert (DOCS / "guides" / f"{entry['guide']}.md").is_file(), entry
        assert f"]({entry['file']})" in readme, f"examples/README.md does not link {entry['file']}"


def _blocks(name: str):
    return BLOCK.findall((DOCS / "tutorials" / name).read_text(encoding="utf-8"))


def test_bulk_rename_excerpts_are_verbatim():
    source = (ROOT / "examples" / "bulk_rename" / "app.py").read_text(encoding="utf-8")
    excerpts = [code for title, code in _blocks("bulk-rename.md") if title == "app.py"]
    assert len(excerpts) >= 8
    for code in excerpts:
        assert code.rstrip("\n") in source, code[:200]


def test_process_dashboard_includes_whole_files():
    folder = ROOT / "examples" / "process_dashboard"
    titled = {title: code for title, code in _blocks("process-dashboard.md") if title}
    assert sorted(titled) == ["dashboard.py", "processes.py", "step1_snapshot.py", "step2_filter.py"]
    for title, code in titled.items():
        assert code == (folder / title).read_text(encoding="utf-8"), title
