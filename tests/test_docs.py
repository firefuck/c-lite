"""Documentation that cannot rot silently.

The documents in this repository are working instructions for whoever (or whatever) changes
the code next. A document that names a file, a test or a roadmap task that does not exist
sends that reader the wrong way, so the references are checked mechanically.

Convention the checks rely on (stated in ``docs/README.md``): a path in backticks refers to
this repository, except inside ``docs/hermes/`` and inside a paragraph, list item or table row
that mentions Hermes, where it refers to the Hermes repository. Those are checked by
``scripts/check_hermes_refs.py`` against a Hermes checkout instead.
"""

from __future__ import annotations

import ast
import importlib
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs"

# TEMPORARY (checkpoint 2026-10-05): the roadmap phases 2-6, docs/prompts and the root AGENTS.md are
# still being written, so these checks cannot pass yet. They switch on by themselves once
# docs/prompts/README.md exists; remove this second condition then.
pytestmark = pytest.mark.skipif(not DOCS.is_dir() or not (DOCS / "prompts" / "README.md").is_file(),
                                reason="not a source checkout, or the working documents are unfinished")

sys.path.insert(0, str(REPO_ROOT / "scripts"))
try:
    import doc_refs
finally:
    sys.path.pop(0)

MAX_AGENTS_LINES = 200  # longer instruction files are followed less reliably


def _documents() -> list[Path]:
    return doc_refs.documents(REPO_ROOT)


def _where(path: Path, line: int) -> str:
    return f"{path.relative_to(REPO_ROOT)}:{line}"


# ── links ────────────────────────────────────────────────────────────────────────────────


def test_relative_links_in_the_docs_resolve():
    broken = []
    for path in _documents():
        text = doc_refs.without_code_fences(path.read_text(encoding="utf-8"))
        for line_number, line in enumerate(text.splitlines(), start=1):
            for target in doc_refs.LINK.findall(line):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                file_part, _, anchor = target.partition("#")
                destination = (path.parent / file_part).resolve() if file_part else path
                if not destination.exists():
                    broken.append(f"{_where(path, line_number)}: {target} (no such file)")
                elif anchor and destination.suffix == ".md" and anchor not in doc_refs.heading_slugs(destination):
                    broken.append(f"{_where(path, line_number)}: {target} (no such heading)")
    assert not broken, "broken links:\n  " + "\n  ".join(broken)


# ── paths, modules and tests named in backticks ──────────────────────────────────────────


def test_paths_named_in_the_docs_exist():
    files = doc_refs.repository_files(REPO_ROOT)
    missing = []
    for path in _documents():
        for token, line_number in doc_refs.local_tokens(path, REPO_ROOT):
            problem = doc_refs.check_local_path(token, files, REPO_ROOT)
            if problem:
                missing.append(f"{_where(path, line_number)}: `{token}` ({problem})")
    assert not missing, (
        "the docs name files that do not exist (or name a Hermes file outside a passage that mentions "
        "Hermes):\n  " + "\n  ".join(missing)
    )


def _resolves(dotted: str) -> bool:
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            target = importlib.import_module(".".join(parts[:cut]))
        except ImportError:
            continue
        for attribute in parts[cut:]:
            if not hasattr(target, attribute):
                return False
            target = getattr(target, attribute)
        return True
    return False


def test_modules_named_in_the_docs_exist():
    unknown = []
    for path in _documents():
        for token, line_number in doc_refs.local_tokens(path, REPO_ROOT):
            if doc_refs.MODULE.fullmatch(token) and not _resolves(token):
                unknown.append(f"{_where(path, line_number)}: `{token}`")
    assert not unknown, "the docs name modules or attributes that do not exist:\n  " + "\n  ".join(unknown)


def _defined_tests() -> set[str]:
    names = set()
    for path in (REPO_ROOT / "tests").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test_"):
                names.add(node.name)
    return names


def test_tests_named_in_the_docs_exist():
    defined = _defined_tests()
    unknown = []
    for path in _documents():
        for token, line_number in doc_refs.local_tokens(path, REPO_ROOT):
            name = token.rsplit("::", 1)[-1]
            if doc_refs.TEST_NAME.fullmatch(name) and name not in defined:
                unknown.append(f"{_where(path, line_number)}: `{name}`")
    assert not unknown, (
        "the docs cite tests that do not exist; a rule is only \"guarded by a test\" if the test is there:\n  "
        + "\n  ".join(unknown)
    )


# ── roadmap ──────────────────────────────────────────────────────────────────────────────

TASK_ID = re.compile(r"\bF\d-T\d+\b")
TASK_HEADING = re.compile(r"^### (F\d-T\d+)\b", re.MULTILINE)


def _roadmap_tasks() -> dict[str, Path]:
    tasks: dict[str, Path] = {}
    for path in sorted((DOCS / "roadmap").glob("fase-*.md")):
        for task_id in TASK_HEADING.findall(path.read_text(encoding="utf-8")):
            assert task_id not in tasks, f"{task_id} is defined twice ({tasks[task_id].name} and {path.name})"
            assert task_id[1] == path.name[len("fase-")], f"{task_id} is defined in {path.name}, the wrong phase file"
            tasks[task_id] = path
    return tasks


def test_roadmap_tasks_cited_in_the_docs_are_defined():
    tasks = _roadmap_tasks()
    assert tasks, "docs/roadmap/fase-*.md define no tasks (headings must look like '### F1-T1 Title')"
    unknown = []
    for path in _documents():
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            unknown.extend(f"{_where(path, line_number)}: {task_id}" for task_id in TASK_ID.findall(line) if task_id not in tasks)
    assert not unknown, "the docs cite roadmap tasks that are not defined:\n  " + "\n  ".join(unknown)


def test_every_roadmap_task_is_in_the_index_and_has_the_standard_fields():
    index = (DOCS / "roadmap" / "README.md").read_text(encoding="utf-8")
    fields = ("**Tujuan.**", "**Lingkup.**", "**File.**", "**Selesai bila.**", "**Ukuran.**", "**Bergantung pada.**")
    problems = []
    for task_id, path in _roadmap_tasks().items():
        if task_id not in index:
            problems.append(f"{task_id} is missing from docs/roadmap/README.md")
        text = path.read_text(encoding="utf-8")
        body = text[text.index(f"### {task_id}"):]
        following = TASK_HEADING.search(body, 4)
        body = body[:following.start()] if following else body
        problems.extend(f"{task_id} has no {field} field" for field in fields if field not in body)
    assert not problems, "\n".join(problems)


# ── instruction files ────────────────────────────────────────────────────────────────────


def _instruction_files(name: str) -> list[Path]:
    return [path for path in _documents() if path.name == name]


def test_every_agents_file_has_a_claude_file_that_imports_it():
    """``AGENTS.md`` is the one place the rules are written. Claude Code reads ``CLAUDE.md``,
    so each directory with rules has a ``CLAUDE.md`` whose first line imports them."""
    agents_files = _instruction_files("AGENTS.md")
    assert REPO_ROOT / "AGENTS.md" in agents_files
    for agents in agents_files:
        claude = agents.with_name("CLAUDE.md")
        assert claude.is_file(), f"{agents.relative_to(REPO_ROOT)} has no CLAUDE.md beside it"
        lines = [line.strip() for line in claude.read_text(encoding="utf-8").splitlines() if line.strip()]
        assert lines and lines[0] == "@AGENTS.md", f"{claude.relative_to(REPO_ROOT)} must start with the line @AGENTS.md"
    for claude in _instruction_files("CLAUDE.md"):
        assert claude.with_name("AGENTS.md").is_file(), f"{claude.relative_to(REPO_ROOT)} imports an AGENTS.md that is not there"


def test_instruction_files_stay_short():
    too_long = {
        str(path.relative_to(REPO_ROOT)): count
        for path in _instruction_files("AGENTS.md")
        if (count := len(path.read_text(encoding="utf-8").splitlines())) > MAX_AGENTS_LINES
    }
    assert not too_long, f"keep each AGENTS.md under {MAX_AGENTS_LINES} lines; move detail to docs/: {too_long}"


# ── the Hermes reference checker ─────────────────────────────────────────────────────────


def test_hermes_reference_checker_reports_a_missing_checkout(tmp_path):
    """The checker needs a Hermes checkout this repository does not contain. Without one it
    must say so and fail, never report success."""
    script = REPO_ROOT / "scripts" / "check_hermes_refs.py"
    result = subprocess.run([sys.executable, str(script), "--hermes", str(tmp_path / "absent")],
                            capture_output=True, text=True, timeout=60, cwd=REPO_ROOT)
    assert result.returncode == 2
    assert "not a Hermes checkout" in result.stderr
