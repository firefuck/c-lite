"""System prompt assembly.

The prompt is built once per session, stored with the session, and reused byte-for-byte on
every request and on resume. That stability is what makes provider-side prompt caching work.
The only event that rebuilds it is context compression.

Three tiers, ordered from least to most likely to differ between sessions, so a provider's
prefix cache covers as much as possible:

``stable``    identity, guidance, auto-loaded skills
``context``   the caller's system message, project instructions, working directory, platform hint
``volatile``  skills index, memory snapshot, plugin sections, date, model

Anything that changes *during* a conversation does not belong here at all. It rides on a
user message or a tool result instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from clite.agent.prompt import identity
from clite.agent.prompt.context_files import DEFAULT_MAX_CHARS, load_project_context, load_soul
from clite.core.config import get_path
from clite.plugins.hooks import get_hook_bus
from clite.skills.catalog import discover_skills, read_skill_file
from clite.skills.index import build_skills_index, visible_skills

logger = logging.getLogger("clite.agent.prompt")


@dataclass
class PromptInputs:
    platform: str = "cli"
    tool_names: frozenset[str] = frozenset()
    toolsets: tuple[str, ...] = ()
    cwd: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    model: str = ""
    provider: str = ""
    context_length: int = 0
    memory_blocks: list[str] = field(default_factory=list)
    system_message: str | None = None
    skip_context_files: bool = False
    depth: int = 0
    profile_name: str = "default"
    now: datetime | None = None


def _context_budget(inputs: PromptInputs) -> int:
    explicit = get_path(inputs.config, "context_file_max_chars")
    if isinstance(explicit, int) and explicit > 0:
        return explicit
    # About 2.5% of the window in characters, never below the default.
    return max(DEFAULT_MAX_CHARS, inputs.context_length // 10) if inputs.context_length else DEFAULT_MAX_CHARS


def _stable(inputs: PromptInputs) -> list[str]:
    tools = inputs.tool_names
    parts = [(None if inputs.skip_context_files else load_soul()) or identity.DEFAULT_IDENTITY]
    if inputs.depth > 0:
        parts.append(identity.SUBAGENT_GUIDANCE)
    if tools:
        parts.append(identity.TOOL_USE_GUIDANCE)
    if "todo" in tools:
        parts.append(identity.TODO_GUIDANCE)
    if "memory" in tools:
        parts.append(identity.MEMORY_GUIDANCE)
    if "session_search" in tools:
        parts.append(identity.SESSION_SEARCH_GUIDANCE)
    if "skill_view" in tools:
        parts.append(identity.SKILLS_GUIDANCE)
    for name in get_path(inputs.config, "skills.auto_load", []) or []:
        skill = next((s for s in discover_skills(cwd=inputs.cwd or None, config=inputs.config) if s.name == name), None)
        if skill is None:
            logger.warning("skills.auto_load names an unknown skill: %s", name)
            continue
        parts.append(f'## Skill "{skill.name}" (always loaded)\n\n{read_skill_file(skill).strip()}')
    return parts


def _platform_hint(inputs: PromptInputs) -> str:
    builtin = identity.PLATFORM_HINTS.get(inputs.platform, "")
    override = (get_path(inputs.config, "platform_hints", {}) or {}).get(inputs.platform)
    if isinstance(override, str):
        return override
    if isinstance(override, dict):
        if "replace" in override:
            return str(override["replace"])
        if "append" in override:
            return f"{builtin}\n{override['append']}".strip()
    return builtin


def _context(inputs: PromptInputs) -> list[str]:
    parts: list[str] = []
    if inputs.system_message:
        parts.append(inputs.system_message.strip())
    if not inputs.skip_context_files:
        project = load_project_context(inputs.cwd or None, _context_budget(inputs))
        if project:
            parts.append(project)
    if inputs.cwd:
        parts.append(f"Working directory: {inputs.cwd}")
    hint = _platform_hint(inputs)
    if hint:
        parts.append(hint)
    return parts


def _today(inputs: PromptInputs) -> str:
    now = inputs.now
    if now is None:
        zone = str(get_path(inputs.config, "timezone", "") or "")
        try:
            now = datetime.now(ZoneInfo(zone)) if zone else datetime.now().astimezone()
        except ZoneInfoNotFoundError:
            now = datetime.now().astimezone()
    # Date only: a clock time would make every session's prompt unique and defeat the cache.
    return now.strftime("%A, %B %d, %Y")


def _volatile(inputs: PromptInputs) -> list[str]:
    parts: list[str] = []
    if "skill_view" in inputs.tool_names:
        skills = visible_skills(
            discover_skills(cwd=inputs.cwd or None, config=inputs.config),
            enabled_tools=inputs.tool_names, enabled_toolsets=inputs.toolsets,
        )
        index = build_skills_index(skills)
        if index:
            parts.append(index)
    parts.extend(block for block in inputs.memory_blocks if block)
    parts.extend(get_hook_bus().render_prompt_sections())
    if inputs.profile_name not in ("", "default"):
        parts.append(f"Active profile: {inputs.profile_name}")
    parts.append(f"Conversation started: {_today(inputs)}")
    if inputs.model:
        parts.append(f"Model: {inputs.model}" + (f" (provider: {inputs.provider})" if inputs.provider else ""))
    return parts


def build_prompt_tiers(inputs: PromptInputs) -> dict[str, list[str]]:
    """The prompt as its three tiers, for inspection (`clite debug prompt`) and tests."""
    return {"stable": _stable(inputs), "context": _context(inputs), "volatile": _volatile(inputs)}


def build_system_prompt(inputs: PromptInputs) -> str:
    tiers = build_prompt_tiers(inputs)
    return "\n\n".join(part.strip() for tier in ("stable", "context", "volatile") for part in tiers[tier] if part and part.strip())
