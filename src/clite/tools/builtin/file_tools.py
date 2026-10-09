"""File tools: read_file, write_file, patch, search_files.

Relative paths resolve against the session's execution environment, so they follow ``cd``
in the terminal. Every read and write goes through that environment's file operations
(``read_file``, ``write_file``, ``list_dir``, ``stat``) rather than touching the host
filesystem directly, so the same four tools work whether the session runs locally, in a
container, or on another machine.
"""

from __future__ import annotations

import difflib
import fnmatch
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any

from clite.core.redact import redact
from clite.tools.checkpoints import record_change, turn_id_for
from clite.tools.context import ToolContext
from clite.tools.environments import get_environment
from clite.tools.file_safety import read_denied_reason, write_denied_reason
from clite.tools.patching import apply_replacement, apply_v4a_patch, find_tolerant_match
from clite.tools.registry import PARALLEL_PATH, PARALLEL_SAFE, registry, tool_error, tool_result

DEFAULT_READ_LIMIT = 500
REDACTION_NOTE = (
    "Credentials in this text were replaced with [REDACTED]. Do not copy that marker into a patch or a file."
)
MAX_LINE_CHARS = 2000
MAX_SEARCH_FILE_BYTES = 2_000_000
# A file bigger than this is read from its first slice only: the tools page through large text,
# and reading a multi-gigabyte file whole to show 500 lines would exhaust memory.
MAX_READ_BYTES = 8_000_000
SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".tox",
        ".idea",
        ".next",
        "target",
    }
)


def _env(ctx: ToolContext):
    return get_environment(ctx.task_id or ctx.session_id, cwd=ctx.cwd)


def _resolve(path: str, ctx: ToolContext) -> str:
    return _env(ctx).resolve_path(path)


def _join(parent: str, name: str) -> str:
    """Join a directory path and a child name using the backend's path spelling."""
    return str(PurePosixPath(parent) / name)


def _before_content(environment, path: str) -> str | None:
    """The file's text as it is now, for the checkpoint store.

    Read through the session environment so a checkpoint follows the same files the tools
    see. A binary or unreadable file has nothing to save: the change is still recorded, and
    the rollback reports that entry as skipped rather than silently doing nothing.
    """
    try:
        read = environment.read_file(path)
    except OSError:
        return None
    return None if read.binary else read.content


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
            "path": {
                "type": "string",
                "description": "File path, absolute or relative to the working directory.",
            },
            "offset": {"type": "integer", "description": "First line to return, 1-based (default 1)."},
            "limit": {
                "type": "integer",
                "description": f"Maximum lines to return (default {DEFAULT_READ_LIMIT}).",
            },
        },
        "required": ["path"],
    },
}


def read_file_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    raw_path = args.get("path")
    if not raw_path:
        return tool_error("path is required")
    environment = _env(ctx)
    path = environment.resolve_path(str(raw_path))
    info = environment.stat(path)
    if not info.exists:
        return tool_error(f"File not found: {path}", suggestions=_similar_names(path, ctx))
    if info.is_dir:
        return tool_error(f"{path} is a directory. Use search_files(target='files') to list it.")
    if not info.is_file:
        return tool_error(f"{path} is not a regular file (a device, pipe or socket) and cannot be read.")
    denied = read_denied_reason(path)
    if denied:
        return tool_error(f"Refused to read {path}: {denied}.")
    try:
        offset = max(1, int(args.get("offset") or 1))
        limit = max(1, int(args.get("limit") or DEFAULT_READ_LIMIT))
    except (TypeError, ValueError):
        return tool_error("offset and limit must be integers")
    try:
        read = environment.read_file(path, max_bytes=MAX_READ_BYTES)
    except OSError as exc:
        return tool_error(f"could not read {path}: {exc}")
    if read.binary:
        return tool_error(f"{path} looks like a binary file ({read.size} bytes) and cannot be read as text.")
    lines = read.content.splitlines()

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
    # What the model reads goes to the model provider and into the session database.
    shown = "\n".join(selected)
    content = redact(shown)
    payload: dict[str, Any] = {"content": content, "path": str(path), "total_lines": len(lines)}
    if content != shown:
        payload["note"] = REDACTION_NOTE
    if last < len(lines):
        payload["truncated"] = True
        payload["next_offset"] = last + 1
        payload["hint"] = f"Showing lines {offset}-{last} of {len(lines)}. Continue with offset={last + 1}."
    return tool_result(payload)


def _similar_names(path: str, ctx: ToolContext) -> list[str]:
    parent = os.path.dirname(path) or "."
    try:
        siblings = [entry.name for entry in _env(ctx).list_dir(parent)]
    except OSError:
        return []
    name = os.path.basename(path)
    return [os.path.join(parent, match) for match in difflib.get_close_matches(name, siblings, n=3, cutoff=0.6)]


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
            "path": {
                "type": "string",
                "description": "File path, absolute or relative to the working directory.",
            },
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
    environment = _env(ctx)
    path = environment.resolve_path(str(raw_path))
    denied = write_denied_reason(path)
    if denied:
        return tool_error(f"Refused to write {path}: {denied}.")
    existed = environment.stat(path).is_file
    # Save the previous content before the write, so /rollback can undo it. Only a real edit
    # is a checkpoint: replacing a file that never existed records a creation instead.
    previous = _before_content(environment, path) if existed else None
    try:
        environment.write_file(path, content)
    except OSError as exc:
        return tool_error(f"could not write {path}: {exc}")
    change = record_change(ctx.session_id, str(path), before=previous, existed=existed, turn=turn_id_for(ctx))
    return tool_result(
        path=str(path),
        bytes_written=len(content.encode("utf-8")),
        created=not existed,
        checkpointed=change is not None and change.skipped_reason is None,
    )


# ── patch ────────────────────────────────────────────────────────────────────────────────

PATCH_SCHEMA = {
    "name": "patch",
    "description": (
        "Replace text in a file, or apply a multi-file V4A patch. In replace mode "
        "(default), old_string must match exactly once (include enough surrounding lines "
        "to make it unique) unless replace_all is true; a tolerant match chain (trailing "
        "whitespace, indentation, smart quotes, blank lines) is tried when the exact text "
        "is absent, each rung only accepted when the match is unique. In patch mode, the "
        "patch argument holds V4A text (*** Update/Add/Delete File) touching several files, "
        "applied atomically: all or nothing. Returns a diff of the change. Read the file "
        "first so old_string is copied from its real content."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File to edit (replace mode)."},
            "old_string": {"type": "string", "description": "Exact text to find (replace mode)."},
            "new_string": {
                "type": "string",
                "description": "Replacement text. Empty string deletes (replace mode).",
            },
            "replace_all": {
                "type": "boolean",
                "description": "Replace every occurrence (default false, replace mode).",
            },
            "mode": {
                "type": "string",
                "enum": ["replace", "patch"],
                "description": (
                    "'replace' (default) edits one file with old_string/new_string. "
                    "'patch' applies the V4A text in the `patch` argument across several files atomically."
                ),
            },
            "patch": {
                "type": "string",
                "description": (
                    "V4A patch text (patch mode only): *** Update/Add/Delete File headers, each followed "
                    "by @@ context @@, - removed lines, + added lines, and ' ' context lines."
                ),
            },
        },
        "required": ["path", "old_string", "new_string"],
    },
}


def _patch_mode(args: dict[str, Any], ctx: ToolContext) -> str:
    """Apply a V4A multi-file patch atomically; all paths still go through ``write_denied_reason``."""
    patch_text = args.get("patch")
    if not isinstance(patch_text, str) or not patch_text.strip():
        return tool_error("mode='patch' requires a non-empty `patch` argument with V4A text")

    def resolve(path_str: str) -> Path:
        return Path(_resolve(path_str, ctx))

    result = apply_v4a_patch(patch_text, resolve)
    if result.error:
        extra: dict[str, Any] = {}
        if result.denied_path:
            extra["denied_path"] = result.denied_path
        if result.rolled_back:
            extra["rolled_back"] = True
        return tool_error(result.error, **extra)

    files: list[dict[str, Any]] = []
    turn = turn_id_for(ctx)
    for entry in result.applied:
        # Record from the snapshot the patch kept: it holds each file's content as it was
        # before this patch, which is exactly what a checkpoint needs. A delete leaves the
        # path gone; a creation had no previous content.
        record_change(
            ctx.session_id,
            str(entry.path),
            before=entry.before,
            existed=entry.before is not None,
            turn=turn,
            deleted=not entry.path.exists(),
        )
        files.append(
            {
                "path": str(entry.path),
                "created": entry.created,
                "diff": redact(entry.diff[:8000]),
            }
        )
    return tool_result(files=files, count=len(files))


def patch_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    mode = args.get("mode") or "replace"
    if mode == "patch":
        return _patch_mode(args, ctx)
    if mode != "replace":
        return tool_error(f"mode must be 'replace' or 'patch', got {mode!r}")

    raw_path, old, new = args.get("path"), args.get("old_string"), args.get("new_string")
    if not raw_path:
        return tool_error("path is required")
    if not isinstance(old, str) or not old:
        return tool_error("old_string is required and must not be empty")
    if not isinstance(new, str):
        return tool_error("new_string is required")
    if old == new:
        return tool_error("old_string and new_string are identical; nothing to change")
    environment = _env(ctx)
    path = environment.resolve_path(str(raw_path))
    denied = write_denied_reason(path)
    if denied:
        return tool_error(f"Refused to edit {path}: {denied}.")
    if not environment.stat(path).is_file:
        return tool_error(f"File not found: {path}")
    try:
        content = environment.read_file(path).content
    except OSError as exc:
        return tool_error(f"could not read {path}: {exc}")

    count = content.count(old)
    if count == 1:
        updated, replaced, level = content.replace(old, new, 1), 1, "exact"
    elif count > 1:
        if not args.get("replace_all"):
            return tool_error(
                f"old_string matches {count} places. Add surrounding lines to make it unique, "
                "or set replace_all=true.",
                path=str(path),
                matches=count,
            )
        updated, replaced, level = content.replace(old, new), count, "exact"
    else:
        # Exact match absent: walk the tolerance chain. Each rung is accepted only when
        # the match is unique; an ambiguous rung stops the chain so the model is told
        # how many candidates the loosest passing normalisation saw.
        match = find_tolerant_match(content, old)
        if not match.found or match.span is None:
            reason = "was not found" if match.matches == 0 else f"matches {match.matches} places"
            return tool_error(
                f"old_string {reason}. Read the file again and copy the text exactly, including indentation.",
                path=str(path),
                matches=match.matches,
            )
        updated = apply_replacement(content, match.span, new)
        replaced, level = 1, match.level

    try:
        environment.write_file(path, updated)
    except OSError as exc:
        return tool_error(f"could not write {path}: {exc}")
    record_change(ctx.session_id, str(path), before=content, existed=True, turn=turn_id_for(ctx))
    diff = "".join(
        difflib.unified_diff(
            content.splitlines(keepends=True),
            updated.splitlines(keepends=True),
            fromfile=f"a/{PurePosixPath(path).name}",
            tofile=f"b/{PurePosixPath(path).name}",
            n=2,
        )
    )
    return tool_result(path=str(path), replacements=replaced, match_level=level, diff=redact(diff[:8000]))


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
            "path": {
                "type": "string",
                "description": "Directory or file to search (default: working directory).",
            },
            "file_glob": {
                "type": "string",
                "description": "Only search files whose name matches, e.g. '*.ts'.",
            },
            "limit": {"type": "integer", "description": "Maximum results (default 50)."},
            "ignore_case": {"type": "boolean", "description": "Case-insensitive match (default false)."},
        },
        "required": ["pattern"],
    },
}


def _ancestors(directory: str) -> list[str]:
    """Every parent of ``directory``, immediate parent first, root last."""
    parents: list[str] = []
    current = PurePosixPath(directory)
    while True:
        parent = current.parent
        if str(parent) == str(current):
            break
        parents.append(str(parent))
        current = parent
    return parents


def _walk(environment, root: str, *, max_depth: int = 40):
    """Yield files under ``root`` in sorted order, skipping dependency/vcs directories.

    Files directly under a directory come before files in its subdirectories, both sorted by
    name (depth-first, directories after files). Cycles (a symlink to an ancestor) are dropped
    by never descending into a directory that is its own ancestor; ``max_depth`` bounds a
    pathologically deep tree.
    """
    if environment.stat(root).is_file:
        yield root
        return
    stack: list[tuple[str, int, frozenset[str]]] = [(root, 0, frozenset(_ancestors(root)))]
    while stack:
        directory, depth, ancestors = stack.pop()
        try:
            entries = environment.list_dir(directory)
        except OSError:
            continue
        subdirs: list[str] = []
        for entry in sorted(entries, key=lambda item: item.name):
            if entry.is_dir:
                if entry.name in SKIP_DIRS or depth >= max_depth:
                    continue
                child = _join(directory, entry.name)
                if child not in ancestors:
                    subdirs.append(child)
            elif entry.is_file:
                yield _join(directory, entry.name)
        for child in reversed(subdirs):
            stack.append((child, depth + 1, ancestors | {child}))


def search_files_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    pattern = args.get("pattern")
    if not isinstance(pattern, str) or not pattern:
        return tool_error("pattern is required")
    target = args.get("target") or "content"
    environment = _env(ctx)
    root = environment.resolve_path(str(args.get("path") or "."))
    root_info = environment.stat(root)
    if not root_info.exists:
        return tool_error(f"Path not found: {root}")
    try:
        limit = max(1, min(int(args.get("limit") or 50), 500))
    except (TypeError, ValueError):
        return tool_error("limit must be an integer")
    file_glob = args.get("file_glob")
    base = root if root_info.is_dir else str(PurePosixPath(root).parent)

    def display(path: str) -> str:
        prefix = base.rstrip("/") + "/"
        return path[len(prefix) :] if path.startswith(prefix) else path

    if target == "files":
        matches = []
        for path in _walk(environment, root):
            name = PurePosixPath(path).name
            if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(display(path), pattern):
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
    for path in _walk(environment, root):
        if file_glob and not fnmatch.fnmatch(PurePosixPath(path).name, str(file_glob)):
            continue
        info = environment.stat(path)
        if info.size > MAX_SEARCH_FILE_BYTES or read_denied_reason(path):
            continue
        try:
            read = environment.read_file(path, max_bytes=MAX_SEARCH_FILE_BYTES + 1)
        except OSError:
            continue
        if read.binary:
            continue
        hit = False
        for number, line in enumerate(read.content.splitlines(), start=1):
            if regex.search(line):
                hit = True
                results.append(f"{display(path)}:{number}: {redact(line.strip()[:300])}")
                if len(results) >= limit:
                    break
        files_with_matches += hit
        if len(results) >= limit:
            break
    return tool_result(
        matches=results,
        count=len(results),
        files_with_matches=files_with_matches,
        truncated=len(results) >= limit,
        root=str(base),
    )


registry.register(
    "read_file",
    "file",
    READ_FILE_SCHEMA,
    read_file_tool,
    emoji="📖",
    parallel=PARALLEL_PATH,
    path_args=("path",),
)
registry.register(
    "write_file",
    "file",
    WRITE_FILE_SCHEMA,
    write_file_tool,
    emoji="✍️",
    parallel=PARALLEL_PATH,
    path_args=("path",),
)
registry.register(
    "patch", "file", PATCH_SCHEMA, patch_tool, emoji="🔧", parallel=PARALLEL_PATH, path_args=("path",)
)
registry.register(
    "search_files", "file", SEARCH_FILES_SCHEMA, search_files_tool, emoji="🔎", parallel=PARALLEL_SAFE
)
