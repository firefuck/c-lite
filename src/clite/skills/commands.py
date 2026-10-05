"""Skills as slash commands: ``/<skill-name> [instruction]``.

The skill is delivered as a *user message*, never by editing the system prompt. Changing the
system prompt mid-conversation would invalidate the provider's prompt cache for every turn
that follows.
"""

from __future__ import annotations

import re
from typing import Any

from clite.skills.catalog import Skill, discover_skills, linked_files, read_skill_file
from clite.skills.usage import record_use

_SLUG_RE = re.compile(r"[^a-z0-9-]+")


def skill_slug(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")


def skill_commands(*, cwd: str | None = None, config: dict[str, Any] | None = None) -> dict[str, Skill]:
    """``{slash command name: skill}`` for every available skill."""
    return {skill_slug(skill.name): skill for skill in discover_skills(cwd=cwd, config=config)}


def build_skill_message(skill: Skill, instruction: str = "") -> str:
    """The user message that loads ``skill`` and carries the user's instruction."""
    record_use(skill.name)
    parts = [
        f'[The user invoked the "{skill.name}" skill. Its instructions follow; apply them to this request.]',
        "",
        read_skill_file(skill).strip(),
    ]
    files = linked_files(skill)
    if files:
        parts += ["", "[This skill has supporting files; load one with skill_view(name, file_path) when you need it:]"]
        parts += [f"- {path}" for paths in files.values() for path in paths]
    parts += ["", f"[Skill directory: {skill.directory}]"]
    if instruction.strip():
        parts += ["", f"The user's instruction for this skill: {instruction.strip()}"]
    return "\n".join(parts)
