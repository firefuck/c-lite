"""The skills index: the only part of the skill system that costs tokens on every request.

Progressive disclosure: the system prompt lists each skill's name and description; the model
calls ``skill_view`` to load one, and again with a file path for a supporting file. A hundred
installed skills cost a hundred short lines, not a hundred documents.
"""

from __future__ import annotations

from collections.abc import Iterable

from clite.skills.catalog import Skill

MAX_INDEX_CHARS = 12_000
MAX_DESCRIPTION_CHARS = 200


def visible_skills(skills: Iterable[Skill], *, enabled_tools: Iterable[str] = (), enabled_toolsets: Iterable[str] = ()) -> list[Skill]:
    """Apply conditional activation.

    ``requires_*``: show only when those tools or toolsets are available (the skill is useless
    without them). ``fallback_for_*``: show only when they are *not* available (the skill is a
    workaround for a missing capability).
    """
    tools, toolsets = set(enabled_tools), set(enabled_toolsets)
    visible = []
    for skill in skills:
        meta = skill.meta
        if any(name not in toolsets for name in meta.requires_toolsets):
            continue
        if any(name not in tools for name in meta.requires_tools):
            continue
        if meta.fallback_for_toolsets and all(name in toolsets for name in meta.fallback_for_toolsets):
            continue
        if meta.fallback_for_tools and all(name in tools for name in meta.fallback_for_tools):
            continue
        visible.append(skill)
    return visible


def build_skills_index(skills: Iterable[Skill]) -> str:
    """The ``<available_skills>`` block, or ``""`` when there is nothing to list."""
    by_category: dict[str, list[Skill]] = {}
    for skill in skills:
        by_category.setdefault(skill.category or "general", []).append(skill)
    if not by_category:
        return ""
    lines = ["<available_skills>"]
    size = 0
    omitted = 0
    for category in sorted(by_category):
        lines.append(f"  {category}:")
        for skill in sorted(by_category[category], key=lambda item: item.name):
            description = skill.description
            if len(description) > MAX_DESCRIPTION_CHARS:
                description = description[: MAX_DESCRIPTION_CHARS - 1].rstrip() + "…"
            line = f"    - {skill.name}: {description}"
            if size + len(line) > MAX_INDEX_CHARS:
                omitted += 1
                continue
            lines.append(line)
            size += len(line)
    if omitted:
        lines.append(f"  ({omitted} more not shown; use skills_list to see all)")
    lines.append("</available_skills>")
    return "\n".join(lines)
