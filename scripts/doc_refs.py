"""Find what the Markdown documents refer to: links, and names written in backticks.

Shared by ``tests/test_docs.py`` (references into this repository) and
``scripts/check_hermes_refs.py`` (references into a Hermes checkout).

The convention both rely on: a path in backticks refers to this repository, except

* anywhere in ``docs/hermes/``, and
* in a paragraph, list item or table row that mentions Hermes by name,

where it refers to the Hermes repository. Two refinements keep mixed passages unambiguous:

* a path starting with ``src/clite/`` or ``docs/`` is always local (Hermes has neither
  directory);
* in a table, the header decides per column: a column whose header names Hermes holds Hermes
  paths, and once a table has such a column (or a column whose header names C-lite) every
  other column follows its header or the document's default instead of the row's wording.
"""

from __future__ import annotations

import os
import re
from pathlib import Path


def _brand() -> tuple[str, str]:
    """``(package name, display name)`` as ``src/<package>/core/brand.py`` states them, so a
    renamed project needs no change here."""
    found = sorted((Path(__file__).resolve().parents[1] / "src").glob("*/core/brand.py"))
    text = found[0].read_text(encoding="utf-8") if found else ""
    name = re.search(r'^APP_NAME = "([^"]+)"', text, re.MULTILINE)
    display = re.search(r'^DISPLAY_NAME = "([^"]+)"', text, re.MULTILINE)
    return (name.group(1) if name else "app"), (display.group(1) if display else "App")


PACKAGE, DISPLAY = _brand()

LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")
TOKEN = re.compile(r"`([^`\n]+)`")
MODULE = re.compile(rf"{re.escape(PACKAGE)}(?:\.[A-Za-z_]\w*)+")
TEST_NAME = re.compile(r"test_[a-z0-9_]+")
HERMES_WORD = re.compile(r"\bHermes\b")
LOCAL_WORD = re.compile(rf"(?<!\w){re.escape(DISPLAY)}(?!\w)")

SKIP_DIRS = frozenset({
    ".git", "node_modules", "build", "dist", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv",
})
# Shipped content (skills, plugin READMEs) is not project documentation.
SKIP_DOC_DIRS = SKIP_DIRS | {"bundled"}
ROOT_PREFIXES = ("src/", "tests/", "scripts/", "docs/", "apps/", "ui-tui/", ".github/")
# Produced by a build step and ignored by git: a document may name them, a checkout lacks them.
BUILD_OUTPUT = ("ui-tui/dist/", "apps/desktop/dist/", "apps/shared/dist/")
CODE_SUFFIXES = (".py", ".ts", ".tsx", ".mjs", ".cjs", ".js", ".sh")
FILE_SUFFIXES = (*CODE_SUFFIXES, ".md", ".json", ".yaml", ".yml", ".toml", ".txt", ".lock", ".ps1", ".nix", ".example")
ALWAYS_LOCAL = (f"src/{PACKAGE}/", "docs/")

_FENCE = re.compile(r"^\s*(```|~~~)")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_NOT_A_PATH = re.compile(r"[\s<>*{}$|=,;]|\.\.\.|…")
_LINE_SUFFIX = re.compile(r":\d+(?:-\d+)?$")


def documents(root: Path) -> list[Path]:
    """Every Markdown document that belongs to the project, sorted."""
    found: list[Path] = []
    for directory, subdirectories, names in os.walk(root):
        subdirectories[:] = [name for name in subdirectories if name not in SKIP_DOC_DIRS]
        found.extend(Path(directory) / name for name in names if name.endswith(".md"))
    return sorted(found)


def repository_files(root: Path) -> set[str]:
    """Relative POSIX paths of every file and directory, without caches and build output."""
    found: set[str] = set()
    for directory, subdirectories, names in os.walk(root):
        subdirectories[:] = [name for name in subdirectories if name not in SKIP_DIRS]
        relative = Path(directory).relative_to(root)
        if relative.parts:
            found.add(relative.as_posix())
        found.update((relative / name).as_posix() for name in names)
    return found


def without_code_fences(text: str) -> str:
    """``text`` with fenced code blocks blanked out; line numbers are unchanged."""
    lines, inside = [], False
    for line in text.splitlines():
        if _FENCE.match(line):
            inside = not inside
            lines.append("")
        else:
            lines.append("" if inside else line)
    return "\n".join(lines)


def heading_slugs(path: Path) -> set[str]:
    """Anchors a renderer generates for the headings of ``path`` (GitHub's rules)."""
    slugs = set()
    for line in without_code_fences(path.read_text(encoding="utf-8")).splitlines():
        if line.startswith("#"):
            title = line.lstrip("#").strip().replace("`", "").lower()
            slugs.add(re.sub(r"[^\w\- ]", "", title).replace(" ", "-"))
    return slugs


def blocks(text: str) -> list[list[tuple[int, str]]]:
    """Paragraphs, list items, table rows and headings, each as ``[(line number, line), ...]``."""
    result: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []

    def close() -> None:
        nonlocal current
        if current:
            result.append(current)
            current = []

    for number, line in enumerate(without_code_fences(text).splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            close()
        elif stripped.startswith(("|", "#")):
            close()
            result.append([(number, line)])
        elif _LIST_ITEM.match(line):
            close()
            current.append((number, line))
        else:
            current.append((number, line))
    close()
    return result


def _cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _column_kinds(header: str) -> list[bool | None]:
    """Per column of a table: True (Hermes), False (local) or None (the header does not say)."""
    return [True if HERMES_WORD.search(cell) else False if LOCAL_WORD.search(cell) else None for cell in _cells(header)]


def _classified(path: Path, root: Path) -> list[tuple[str, int, bool]]:
    """``(token, line, refers_to_hermes)`` for every backticked name in ``path``."""
    in_hermes_docs = path.relative_to(root).as_posix().startswith("docs/hermes/")
    found: list[tuple[str, int, bool]] = []
    columns: list[bool | None] = []  # of the table being read
    last_row = 0
    for block in blocks(path.read_text(encoding="utf-8")):
        number, line = block[0]
        if line.strip().startswith("|"):
            if number != last_row + 1:
                columns = _column_kinds(line)  # the header row of a new table
            last_row = number
            labelled = any(kind is not None for kind in columns)
            row_default = in_hermes_docs if labelled else in_hermes_docs or bool(HERMES_WORD.search(line))
            for index, cell in enumerate(_cells(line)):
                kind = columns[index] if index < len(columns) else None
                hermes = row_default if kind is None else kind
                found.extend((token, number, hermes and not token.startswith(ALWAYS_LOCAL)) for token in TOKEN.findall(cell))
            continue
        hermes_block = in_hermes_docs or any(HERMES_WORD.search(text) for _, text in block)
        for number, line in block:
            found.extend((token, number, hermes_block and not token.startswith(ALWAYS_LOCAL)) for token in TOKEN.findall(line))
    return found


def local_tokens(path: Path, root: Path) -> list[tuple[str, int]]:
    """Backticked names that refer to this repository."""
    return [(token, line) for token, line, hermes in _classified(path, root) if not hermes]


def hermes_tokens(path: Path, root: Path) -> list[tuple[str, int]]:
    """Backticked names that refer to the Hermes repository."""
    return [(token, line) for token, line, hermes in _classified(path, root) if hermes]


def normalize(token: str) -> str | None:
    """``token`` as a relative path, or ``None`` when it is not one that can be checked
    (a placeholder such as ``<name>``, a glob, a home path, a URL, a command line)."""
    text = token.strip().strip("()").rstrip(".,:")
    text = text.split("::", 1)[0]
    text = _LINE_SUFFIX.sub("", text)
    if not text or _NOT_A_PATH.search(text) or text.startswith(("~", "/", "http", "./", "../", "-", "@", "#")):
        return None
    return text


def _ends_with(path: str, files: set[str]) -> bool:
    return path in files or any(name.endswith("/" + path) for name in files)


def check_local_path(token: str, files: set[str], root: Path) -> str | None:
    """Why ``token`` does not name something in this repository, or ``None`` when it does
    (or when it is not a path this check understands).

    * A path from the repository root (``src/clite/...``, ``tests/...``, ``docs/...``) must
      exist exactly.
    * ``src/...`` may also be relative to a package (``src/plain.ts`` in ``ui-tui``), and a
      shorter path or a bare file name (``turn/context.py``, ``loop.py``) is relative to
      whatever directory the passage is about: some file must end with it.
    * Only source files are checked that way. ``config.yaml`` or ``SKILL.md`` name files in
      the user's home, not in the repository.
    """
    path = normalize(token)
    if path is None or (path.startswith(".") and not path.startswith(".github/")):
        return None
    if path.startswith(BUILD_OUTPUT) or path.startswith("dist/") or "/dist/" in path:
        return None
    if path.startswith(ROOT_PREFIXES) and not (path.startswith("src/") and not path.startswith(f"src/{PACKAGE}")):
        return None if path.rstrip("/") in files else "not in the repository"
    if path.startswith("src/"):
        return None if _ends_with(path.rstrip("/"), files) else "no package has this path"
    if not path.endswith(CODE_SUFFIXES) or not re.fullmatch(r"[\w.\-/]+", path):
        return None
    if _ends_with(path, files):
        return None
    return "no file ends with this path" if "/" in path else "no file has this name"
