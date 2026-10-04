"""Skill tools: list, view (progressive disclosure), and manage (procedural memory)."""

from __future__ import annotations

from typing import Any

from clite.skills import manager
from clite.skills.catalog import discover_skills, get_skill, linked_files, read_skill_file
from clite.skills.manager import SkillError
from clite.skills.usage import record_use
from clite.tools.context import ToolContext
from clite.tools.registry import PARALLEL_SAFE, registry, tool_error, tool_result

SKILLS_LIST_SCHEMA = {
    "name": "skills_list",
    "description": "List available skills with their descriptions. Use it when the index in the system prompt was truncated or you want to filter by category.",
    "parameters": {
        "type": "object",
        "properties": {"category": {"type": "string", "description": "Only skills in this category."}},
    },
}

SKILL_VIEW_SCHEMA = {
    "name": "skill_view",
    "description": (
        "Load a skill's full instructions. Call this before starting any task a skill covers. Pass "
        "file_path to load one of the skill's supporting files (references/, templates/, scripts/, assets/)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Skill name from the index."},
            "file_path": {"type": "string", "description": "Supporting file to load instead of SKILL.md, e.g. references/api.md."},
        },
        "required": ["name"],
    },
}

SKILL_MANAGE_SCHEMA = {
    "name": "skill_manage",
    "description": (
        "Create and maintain skills: your procedural memory. Save a skill after solving a non-trivial "
        "task in a reusable way, and patch a skill the moment you find it wrong or incomplete. Actions: "
        "'create' (name, content = full SKILL.md with frontmatter), 'patch' (name, old_string, new_string; "
        "preferred for changes), 'edit' (name, content = full replacement), 'delete' (name), "
        "'write_file' (name, file_path, file_content), 'remove_file' (name, file_path)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["create", "patch", "edit", "delete", "write_file", "remove_file"]},
            "name": {"type": "string", "description": "Skill name: lowercase letters, digits, dots, hyphens, underscores."},
            "content": {"type": "string", "description": "Full SKILL.md text, starting with the --- frontmatter (name, description)."},
            "category": {"type": "string", "description": "For create: optional category directory."},
            "old_string": {"type": "string", "description": "For patch: exact text to replace."},
            "new_string": {"type": "string", "description": "For patch: replacement text."},
            "replace_all": {"type": "boolean", "description": "For patch: replace every occurrence."},
            "file_path": {"type": "string", "description": "Supporting file path under references/, templates/, scripts/ or assets/."},
            "file_content": {"type": "string", "description": "For write_file: the file's content."},
        },
        "required": ["action", "name"],
    },
}


def skills_list_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    category = args.get("category")
    skills = [
        skill.summary()
        for skill in discover_skills(cwd=ctx.cwd or None, config=ctx.config)
        if not category or skill.category == category
    ]
    return tool_result(skills=skills, count=len(skills))


def skill_view_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    name = str(args.get("name") or "")
    skill = get_skill(name, cwd=ctx.cwd or None, config=ctx.config)
    if skill is None:
        names = [s.name for s in discover_skills(cwd=ctx.cwd or None, config=ctx.config)]
        return tool_error(f"Skill {name!r} not found.", available=names[:50])
    file_path = args.get("file_path") or None
    try:
        content = read_skill_file(skill, file_path)
    except (PermissionError, FileNotFoundError) as exc:
        return tool_error(str(exc), linked_files=linked_files(skill))
    record_use(skill.name)
    if file_path:
        return tool_result(name=skill.name, file_path=file_path, content=content)
    return tool_result(name=skill.name, description=skill.description, content=content,
                       skill_dir=str(skill.directory), linked_files=linked_files(skill), tier=skill.tier)


def skill_manage_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    action, name = args.get("action"), str(args.get("name") or "")
    try:
        if action == "create":
            result = manager.create_skill(name, str(args.get("content") or ""), category=args.get("category") or None)
        elif action == "edit":
            result = manager.edit_skill(name, str(args.get("content") or ""))
        elif action == "patch":
            result = manager.patch_skill(
                name, str(args.get("old_string") or ""), str(args.get("new_string") or ""),
                file_path=args.get("file_path") or None, replace_all=bool(args.get("replace_all")),
            )
        elif action == "delete":
            result = manager.delete_skill(name)
        elif action == "write_file":
            result = manager.write_skill_file(name, str(args.get("file_path") or ""), str(args.get("file_content") or ""))
        elif action == "remove_file":
            result = manager.remove_skill_file(name, str(args.get("file_path") or ""))
        else:
            return tool_error(f"Unknown action {action!r}. Use create, patch, edit, delete, write_file or remove_file.")
    except SkillError as exc:
        return tool_error(str(exc))
    return tool_result(result, success=True)


registry.register("skills_list", "skills", SKILLS_LIST_SCHEMA, skills_list_tool, emoji="📚", parallel=PARALLEL_SAFE)
registry.register("skill_view", "skills", SKILL_VIEW_SCHEMA, skill_view_tool, emoji="📖", parallel=PARALLEL_SAFE)
registry.register("skill_manage", "skills", SKILL_MANAGE_SCHEMA, skill_manage_tool, emoji="🧩")
