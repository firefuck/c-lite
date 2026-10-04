"""Skill writes: create, patch, rewrite, delete, and supporting files.

Used by the ``skill_manage`` tool (the agent maintaining its own procedural memory) and by
``clite skills``. Every write is validated first and written atomically, and only the local
tier is writable. Editing a skill from a read-only tier copies it to the local tier first.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from clite.core.constants import ensure_dir, get_skills_dir
from clite.core.io import atomic_write_text
from clite.core.threats import describe, scan_text
from clite.plugins.hooks import invoke_hook
from clite.skills.catalog import LINKED_DIRS, TIER_LOCAL, Skill, get_skill
from clite.skills.frontmatter import SkillFormatError, parse_skill_text, validate_skill_name

logger = logging.getLogger("clite.skills.manager")

MAX_SUPPORT_FILE_CHARS = 1_000_000


class SkillError(Exception):
    """A skill operation was refused. The message is written for the model to act on."""


def _check_content(content: str, *, expected_name: str) -> None:
    try:
        parse_skill_text(content, expected_name=expected_name)
    except SkillFormatError as exc:
        raise SkillError(str(exc)) from exc
    threats = scan_text(content)
    if threats:
        raise SkillError(f"skill content was rejected by the security scan ({describe(threats)})")


def _local_dir(name: str, category: str | None) -> Path:
    root = get_skills_dir()
    if category:
        validate_skill_name(category)
        return root / category / name
    return root / name


def _require(name: str, cwd: str | None = None) -> Skill:
    skill = get_skill(name, cwd=cwd)
    if skill is None:
        raise SkillError(f"skill {name!r} does not exist; use skills_list to see what is available")
    return skill


def _writable(skill: Skill) -> Skill:
    """``skill`` in the local tier, copying it there first when it lives in a read-only tier."""
    if skill.tier == TIER_LOCAL:
        return skill
    target = _local_dir(skill.name, skill.category or None)
    if target.exists():
        raise SkillError(f"cannot copy {skill.name!r} to the local tier: {target} already exists")
    ensure_dir(target.parent)
    shutil.copytree(skill.directory, target)
    logger.info("copied %s skill %s to the local tier for editing", skill.tier, skill.name)
    return Skill(skill.name, skill.description, target, TIER_LOCAL, skill.category, skill.meta)


def _notify(action: str, name: str, origin: str) -> None:
    invoke_hook("on_skill_lifecycle", action=action, skill_name=name, origin=origin)


def create_skill(name: str, content: str, *, category: str | None = None, origin: str = "agent") -> dict[str, Any]:
    try:
        validate_skill_name(name)
    except SkillFormatError as exc:
        raise SkillError(str(exc)) from exc
    existing = get_skill(name)
    if existing is not None and existing.tier == TIER_LOCAL:
        raise SkillError(f"skill {name!r} already exists; use action='patch' or 'edit' to change it")
    _check_content(content, expected_name=name)
    directory = _local_dir(name, category)
    atomic_write_text(directory / "SKILL.md", content)
    _record_origin(name, origin)
    _notify("create", name, origin)
    return {"name": name, "path": str(directory / "SKILL.md"), "created": True}


def edit_skill(name: str, content: str, *, origin: str = "agent") -> dict[str, Any]:
    """Replace the whole SKILL.md."""
    skill = _writable(_require(name))
    _check_content(content, expected_name=name)
    atomic_write_text(skill.file, content)
    _notify("edit", name, origin)
    return {"name": name, "path": str(skill.file), "updated": True}


def patch_skill(name: str, old_string: str, new_string: str, *, file_path: str | None = None,
                replace_all: bool = False, origin: str = "agent") -> dict[str, Any]:
    """Replace text in SKILL.md or a supporting file. Preferred over ``edit``: it cannot
    drop the rest of the document."""
    if not old_string:
        raise SkillError("old_string is required")
    skill = _writable(_require(name))
    target = _support_path(skill, file_path) if file_path else skill.file
    if not target.is_file():
        raise SkillError(f"{file_path!r} does not exist in skill {name!r}")
    current = target.read_text(encoding="utf-8")
    count = current.count(old_string)
    if count == 0:
        raise SkillError("old_string was not found; view the skill again and copy the text exactly")
    if count > 1 and not replace_all:
        raise SkillError(f"old_string matches {count} places; add context to make it unique or set replace_all=true")
    updated = current.replace(old_string, new_string)
    if target == skill.file:
        _check_content(updated, expected_name=name)
    else:
        _check_support_content(updated)
    atomic_write_text(target, updated)
    _notify("patch", name, origin)
    return {"name": name, "path": str(target), "replacements": count}


def delete_skill(name: str, *, origin: str = "agent") -> dict[str, Any]:
    skill = _require(name)
    if skill.tier != TIER_LOCAL:
        raise SkillError(
            f"skill {name!r} comes from the {skill.tier} tier and cannot be deleted; "
            "add it to skills.disabled in config.yaml to hide it"
        )
    shutil.rmtree(skill.directory)
    _notify("delete", name, origin)
    return {"name": name, "deleted": True}


def _support_path(skill: Skill, file_path: str) -> Path:
    relative = Path(file_path)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] not in LINKED_DIRS:
        raise SkillError(f"supporting files must live under one of: {', '.join(LINKED_DIRS)}")
    return skill.directory / relative


def _check_support_content(content: str) -> None:
    if len(content) > MAX_SUPPORT_FILE_CHARS:
        raise SkillError(f"supporting file is larger than {MAX_SUPPORT_FILE_CHARS} characters")
    threats = scan_text(content)
    if threats:
        raise SkillError(f"file content was rejected by the security scan ({describe(threats)})")


def write_skill_file(name: str, file_path: str, content: str, *, origin: str = "agent") -> dict[str, Any]:
    skill = _writable(_require(name))
    target = _support_path(skill, file_path)
    _check_support_content(content)
    atomic_write_text(target, content)
    _notify("write_file", name, origin)
    return {"name": name, "path": str(target), "written": True}


def remove_skill_file(name: str, file_path: str, *, origin: str = "agent") -> dict[str, Any]:
    skill = _writable(_require(name))
    target = _support_path(skill, file_path)
    if not target.is_file():
        raise SkillError(f"{file_path!r} does not exist in skill {name!r}")
    target.unlink()
    _notify("remove_file", name, origin)
    return {"name": name, "path": str(target), "removed": True}


def _record_origin(name: str, origin: str) -> None:
    from clite.skills.usage import record_created

    record_created(name, origin)
