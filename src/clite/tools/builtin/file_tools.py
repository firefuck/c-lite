"""File tools: read_file, write_file, patch, search_files.

Relative paths resolve against the session's execution environment, so they follow ``cd``
in the terminal. These are the local implementations; a remote backend would route the same
four operations through its own environment.
"""

from __future__ import annotations

import difflib
import fnmatch
import os
import re
from pathlib import Path
from typing import Any

from clite.core.io import atomic_write_text
from clite.tools.context import ToolContext
from clite.tools.environments import get_environment
from clite.tools.file_safety import write_denied_reason
from clite.tools.registry import PARALLEL_PATH, PARALLEL_SAFE, registry, tool_error, tool_result

DEFAULT_READ_LIMIT = 500
MAX_LINE_CHARS = 2000
MAX_SEARCH_FILE_BYTES = 2_000_000
SKIP_DIRS = frozenset({".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache",
                       ".ruff_cache", "dist", "build", ".tox", ".idea", ".next", "target"})


def _resolve(path: str, ctx: ToolContext) -> Path:
    return Path(get_environment(ctx.task_id or ctx.session_id, cwd=ctx.cwd).resolve_path(path))


def _looks_binary(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return b"\x00" in handle.read(4096)
    except OSError:
        return False


# ── read_file ────────────────────────────────────────────────────────────────────────────

READ_FILE_SCHEMA = {
    "name": "read_file",
    "description": (
        "Read a text file with line numbers (`LINE|content`). Large files are paged: pass offset "
        "(1-based first line) and limit. The result says how many lines the file has and where to "
        "continue. Use this instead of cat/head/tail."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, absolute or relative to the working directory."},
            "offset": {"type": "integer", "description": "First line to return, 1-based (default 1)."},
            "limit": {"type": "integer", "description": f"Maximum lines to return (default {DEFAULT_READ_LIMIT})."},
        },
        "required": ["path"],
    },
}


def read_file_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    raw_path = args.get("path")
    if not raw_path:
        return tool_error("path is required")
    path = _resolve(str(raw_path), ctx)
    if not path.exists():
        return tool_error(f"File not found: {path}", suggestions=_similar_names(path))
    if path.is_dir():
        return tool_error(f"{path} is a directory. Use search_files(target='files') to list it.")
    if _looks_binary(path):
        return tool_error(f"{path} looks like a binary file ({path.stat().st_size} bytes) and cannot be read as text.")
    try:
        offset = max(1, int(args.get("offset") or 1))
        limit = max(1, int(args.get("limit") or DEFAULT_READ_LIMIT))
    except (TypeError, ValueError):
        return tool_error("offset and limit must be integers")
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return tool_error(f"could not read {path}: {exc}")

    budget = int(ctx.setting("file_read_max_chars", 100_000) or 100_000)
    selected: list[str] = []
    used = 0
    for number, line in enumerate(lines[offset - 1 : offset - 1 + limit], start=offset):
        if len(line) > MAX_LINE_CHARS:
            line = line[:MAX_LINE_CHARS] + f" [line truncated, {len(line)} chars]"
        rendered = f"{number}|{line}"
        if used + len(rendered) > budget and selected:
            break
        selected.append(rendered)
        used += len(rendered) + 1
    last = offset + len(selected) - 1
    payload: dict[str, Any] = {"content": "\n".join(selected), "path": str(path), "total_lines": len(lines)}
    if last < len(lines):
        payload["truncated"] = True
        payload["next_offset"] = last + 1
        payload["hint"] = f"Showing lines {offset}-{last} of {len(lines)}. Continue with offset={last + 1}."
    return tool_result(payload)


def _similar_names(path: Path) -> list[str]:
    try:
        siblings = [entry.name for entry in path.parent.iterdir()]
    except OSError:
        return []
    return [str(path.parent / name) for name in difflib.get_close_matches(path.name, siblings, n=3, cutoff=0.6)]


# ── write_file ───────────────────────────────────────────────────────────────────────────

WRITE_FILE_SCHEMA = {
    "name": "write_file",
    "description": (
        "Create a file or replace its whole content. Parent directories are created. To change part "
        "of an existing file use patch instead: it is cheaper and cannot drop the rest of the file."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, absolute or relative to the working directory."},
            "content": {"type": "string", "description": "The complete new content of the file."},
        },
        "required": ["path", "content"],
    },
}


def write_file_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    raw_path, content = args.get("path"), args.get("content")
    if not raw_path:
        return tool_error("path is required")
    if not isinstance(content, str):
        return tool_error("content is required and must be a string")
    path = _resolve(str(raw_path), ctx)
    denied = write_denied_reason(path)
    if denied:
        return tool_error(f"Refused to write {path}: {denied}.")
    existed = path.exists()
    if existed and path.is_dir():
        return tool_error(f"{path} is a directory")
    try:
        atomic_write_text(path, content)
    except OSError as exc:
        return tool_error(f"could not write {path}: {exc}")
    return tool_result(path=str(path), bytes_written=len(content.encode("utf-8")), created=not existed)


# ── patch ────────────────────────────────────────────────────────────────────────────────

PATCH_SCHEMA = {
    "name": "patch",
    "description": (
        "Replace text in a file. old_string must match exactly once (include enough surrounding lines "
        "to make it unique) unless replace_all is true. Returns a diff of the change. Read the file "
        "first so old_string is copied from its real content."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File to edit."},
            "old_string": {"type": "string", "description": "Exact text to find."},
            "new_string": {"type": "string", "description": "Replacement text. Empty string deletes."},
            "replace_all": {"type": "boolean", "description": "Replace every occurrence (default false)."},
        },
        "required": ["path", "old_string", "new_string"],
    },
}


def _find_whitespace_tolerant(content: str, old: str) -> tuple[int, int] | None:
    """Span of the one place where ``old`` matches line by line ignoring leading and trailing
    whitespace. Models routinely get indentation slightly wrong; a unique such match is safe."""
    wanted = [line.strip() for line in old.strip("\n").splitlines()]
    if not wanted or not any(wanted):
        return None
    lines = content.splitlines(keepends=True)
    spans = []
    for start in range(len(lines) - len(wanted) + 1):
        if all(lines[start + i].strip() == wanted[i] for i in range(len(wanted))):
            begin = sum(len(line) for line in lines[:start])
            end = begin + sum(len(line) for line in lines[start : start + len(wanted)])
            spans.append((begin, end))
    return spans[0] if len(spans) == 1 else None


def patch_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    raw_path, old, new = args.get("path"), args.get("old_string"), args.get("new_string")
    if not raw_path:
        return tool_error("path is required")
    if not isinstance(old, str) or not old:
        return tool_error("old_string is required and must not be empty")
    if not isinstance(new, str):
        return tool_error("new_string is required")
    if old == new:
        return tool_error("old_string and new_string are identical; nothing to change")
    path = _resolve(str(raw_path), ctx)
    denied = write_denied_reason(path)
    if denied:
        return tool_error(f"Refused to edit {path}: {denied}.")
    if not path.is_file():
        return tool_error(f"File not found: {path}")
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return tool_error(f"could not read {path}: {exc}")

    count = content.count(old)
    if count == 0:
        span = _find_whitespace_tolerant(content, old)
        if span is None:
            return tool_error(
                "old_string was not found in the file. Read the file again and copy the text exactly, "
                "including indentation.",
                path=str(path),
            )
        replacement = new if new.endswith("\n") or not content[span[0] : span[1]].endswith("\n") else new + "\n"
        updated, replaced = content[: span[0]] + replacement + content[span[1] :], 1
    elif count > 1 and not args.get("replace_all"):
        return tool_error(
            f"old_string matches {count} places. Add surrounding lines to make it unique, or set replace_all=true.",
            path=str(path), matches=count,
        )
    else:
        updated, replaced = content.replace(old, new), count
    try:
        atomic_write_text(path, updated)
    except OSError as exc:
        return tool_error(f"could not write {path}: {exc}")
    diff = "".join(
        difflib.unified_diff(content.splitlines(keepends=True), updated.splitlines(keepends=True),
                             fromfile=f"a/{path.name}", tofile=f"b/{path.name}", n=2)
    )
    return tool_result(path=str(path), replacements=replaced, diff=diff[:8000])


# ── search_files ─────────────────────────────────────────────────────────────────────────

SEARCH_FILES_SCHEMA = {
    "name": "search_files",
    "description": (
        "Search the project. target='content' finds lines matching a regular expression and returns "
        "`path:line: text`. target='files' lists files whose name matches a glob (e.g. '*.py'). "
        "Version-control and dependency directories are skipped. Use this instead of grep, find or ls."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Regex for content search; glob for file search."},
            "target": {"type": "string", "enum": ["content", "files"], "description": "Default 'content'."},
            "path": {"type": "string", "description": "Directory or file to search (default: working directory)."},
            "file_glob": {"type": "string", "description": "Only search files whose name matches, e.g. '*.ts'."},
            "limit": {"type": "integer", "description": "Maximum results (default 50)."},
            "ignore_case": {"type": "boolean", "description": "Case-insensitive match (default false)."},
        },
        "required": ["pattern"],
    },
}


def _walk(root: Path):
    if root.is_file():
        yield root
        return
    for directory, subdirs, files in os.walk(root):
        subdirs[:] = sorted(d for d in subdirs if d not in SKIP_DIRS)
        for name in sorted(files):
            yield Path(directory) / name


def search_files_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    pattern = args.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return tool_error("pattern is required")
    target = args.get("target") or "content"
    root = _resolve(str(args.get("path") or "."), ctx)
    if not root.exists():
        return tool_error(f"Path not found: {root}")
    try:
        limit = max(1, min(int(args.get("limit") or 50), 500))
    except (TypeError, ValueError):
        return tool_error("limit must be an integer")
    file_glob = args.get("file_glob")
    base = root if root.is_dir() else root.parent

    def display(path: Path) -> str:
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            return str(path)

    if target == "files":
        matches = []
        for path in _walk(root):
            if fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(display(path), pattern):
                matches.append(display(path))
                if len(matches) >= limit:
                    break
        return tool_result(files=matches, count=len(matches), truncated=len(matches) >= limit, root=str(base))
    if target != "content":
        return tool_error("target must be 'content' or 'files'")

    try:
        regex = re.compile(pattern, re.IGNORECASE if args.get("ignore_case") else 0)
    except re.error as exc:
        return tool_error(f"invalid regular expression: {exc}")
    results: list[str] = []
    files_with_matches = 0
    for path in _walk(root):
        if file_glob and not fnmatch.fnmatch(path.name, str(file_glob)):
            continue
        try:
            if path.stat().st_size > MAX_SEARCH_FILE_BYTES or _looks_binary(path):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hit = False
        for number, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                hit = True
                results.append(f"{display(path)}:{number}: {line.strip()[:300]}")
                if len(results) >= limit:
                    break
        files_with_matches += hit
        if len(results) >= limit:
            break
    return tool_result(matches=results, count=len(results), files_with_matches=files_with_matches,
                       truncated=len(results) >= limit, root=str(base))


registry.register("read_file", "file", READ_FILE_SCHEMA, read_file_tool, emoji="📖",
                  parallel=PARALLEL_PATH, path_args=("path",))
registry.register("write_file", "file", WRITE_FILE_SCHEMA, write_file_tool, emoji="✍️",
                  parallel=PARALLEL_PATH, path_args=("path",))
registry.register("patch", "file", PATCH_SCHEMA, patch_tool, emoji="🔧", parallel=PARALLEL_PATH, path_args=("path",))
registry.register("search_files", "file", SEARCH_FILES_SCHEMA, search_files_tool, emoji="🔎", parallel=PARALLEL_SAFE)
