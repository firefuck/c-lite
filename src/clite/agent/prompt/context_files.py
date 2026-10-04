"""Context files: SOUL.md (identity) and project instructions.

Only one kind of project file is loaded, the first found in this order: ``.clite.md`` /
``CLITE.md``, then ``AGENTS.md``, then ``CLAUDE.md``, then ``.cursorrules``. Loading all of
them would mostly duplicate the same instructions.

Every file is scanned before it is loaded (a cloned repository is untrusted input) and
truncated to a budget (the prompt is paid for on every request).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from clite.core.brand import PROJECT_CONTEXT_FILENAMES
from clite.core.constants import get_soul_path
from clite.core.threats import describe, scan_text
from clite.skills.catalog import find_project_root

logger = logging.getLogger("clite.agent.prompt")

DEFAULT_MAX_CHARS = 20_000
_HEAD_SHARE, _TAIL_SHARE = 0.7, 0.2
_CHAIN_FILES = ("AGENTS.md", "agents.md")
_SINGLE_FILES = ("CLAUDE.md", ".cursorrules")


def truncate_middle(text: str, limit: int, label: str) -> str:
    """Keep the head and the tail; say what was dropped and where the full file is."""
    if len(text) <= limit:
        return text
    head, tail = int(limit * _HEAD_SHARE), int(limit * _TAIL_SHARE)
    return (
        text[:head]
        + f"\n\n[... {label} truncated: {len(text) - head - tail} of {len(text)} characters omitted. "
        "Read the file for the rest ...]\n\n"
        + text[-tail:]
    )


def _load(path: Path, limit: int) -> str | None:
    """File content, scanned and truncated. ``None`` when missing or empty."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text:
        return None
    threats = scan_text(text)
    if threats:
        logger.warning("blocked context file %s: %s", path, describe(threats))
        return f"[BLOCKED: {path.name} contained possible prompt injection ({describe(threats)}). It was not loaded.]"
    return truncate_middle(text, limit, path.name)


def load_soul(limit: int = DEFAULT_MAX_CHARS) -> str | None:
    """The user's identity file for the active profile, or ``None`` to use the default."""
    return _load(get_soul_path(), limit)


def _ancestors(cwd: Path) -> list[Path]:
    """Directories from the project root down to ``cwd`` (just ``cwd`` outside a repository)."""
    root = find_project_root(cwd)
    if root is None:
        return [cwd]
    chain = [cwd]
    while chain[-1] != root and root in chain[-1].parents:
        chain.append(chain[-1].parent)
    return list(reversed(chain))


def load_project_context(cwd: str | os.PathLike[str] | None = None, limit: int = DEFAULT_MAX_CHARS) -> str:
    """The project's instruction block for the system prompt, or ``""``."""
    directory = Path(cwd or os.getcwd()).resolve()
    chain = _ancestors(directory)

    # 1. The agent's own file: nearest one wins.
    for folder in reversed(chain):
        for name in PROJECT_CONTEXT_FILENAMES:
            content = _load(folder / name, limit)
            if content:
                return f"## Project instructions ({name})\n\n{content}"

    # 2. AGENTS.md: every level from the root down applies, most general first.
    sections = []
    for folder in chain:
        for name in _CHAIN_FILES:
            content = _load(folder / name, limit)
            if content:
                label = name if folder == chain[0] else f"{folder.relative_to(chain[0]).as_posix()}/{name}"
                sections.append(f"## Project instructions ({label})\n\n{content}")
                break
    if sections:
        return truncate_middle("\n\n".join(sections), limit * 2, "project instructions")

    # 3. Files written for other agents, in the working directory only.
    for name in _SINGLE_FILES:
        content = _load(directory / name, limit)
        if content:
            return f"## Project instructions ({name})\n\n{content}"
    return ""
