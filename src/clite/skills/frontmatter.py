"""SKILL.md parsing and validation.

A skill is a directory with a ``SKILL.md``: YAML frontmatter, then Markdown instructions.
The format follows the agentskills.io convention so skills written for other agents load
here unchanged. Agent-specific fields live under ``metadata.<agent>``; both
``metadata.clite`` and ``metadata.hermes`` are read.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from clite.core.brand import SKILL_METADATA_KEYS

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_SKILL_CHARS = 100_000
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_FRONTMATTER_RE = re.compile(r"\A﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.DOTALL)
_HOST = {"linux": "linux", "darwin": "macos", "win32": "windows"}.get(sys.platform, sys.platform)


class SkillFormatError(ValueError):
    """The SKILL.md is not a valid skill."""


@dataclass
class SkillMeta:
    name: str
    description: str
    version: str = ""
    author: str = ""
    license: str = ""
    platforms: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    category: str = ""
    requires_toolsets: tuple[str, ...] = ()
    fallback_for_toolsets: tuple[str, ...] = ()
    requires_tools: tuple[str, ...] = ()
    fallback_for_tools: tuple[str, ...] = ()
    env_passthrough: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


def validate_skill_name(name: Any) -> str:
    if not isinstance(name, str) or not name:
        raise SkillFormatError("skill name is required")
    if len(name) > MAX_NAME_LENGTH:
        raise SkillFormatError(f"skill name is longer than {MAX_NAME_LENGTH} characters")
    if not _NAME_RE.match(name):
        raise SkillFormatError(
            f"invalid skill name {name!r}: use lowercase letters, digits, dots, hyphens and underscores, "
            "starting with a letter or digit"
        )
    return name


def _strings(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """``(frontmatter, body)``. Raises when the frontmatter block is missing or not a mapping."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise SkillFormatError("SKILL.md must start with a YAML frontmatter block between '---' lines")
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        raise SkillFormatError(f"frontmatter is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise SkillFormatError("frontmatter must be a YAML mapping")
    return data, text[match.end():]


def parse_skill_text(text: str, *, expected_name: str | None = None) -> tuple[SkillMeta, str]:
    """Parse and validate. ``expected_name`` (the directory name) must match ``name``."""
    if len(text) > MAX_SKILL_CHARS:
        raise SkillFormatError(f"SKILL.md is larger than {MAX_SKILL_CHARS} characters; move detail into references/")
    data, body = split_frontmatter(text)
    name = validate_skill_name(data.get("name"))
    if expected_name is not None and name != expected_name:
        raise SkillFormatError(f"frontmatter name {name!r} does not match the skill directory {expected_name!r}")
    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        raise SkillFormatError("skill description is required: it is what the model reads to decide when to load the skill")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        raise SkillFormatError(f"description is longer than {MAX_DESCRIPTION_LENGTH} characters")
    if not body.strip():
        raise SkillFormatError("SKILL.md has no instructions after the frontmatter")

    raw_metadata = data.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    agent: dict[str, Any] = {}
    for key in reversed(SKILL_METADATA_KEYS):  # the first key in the tuple wins
        if isinstance(metadata.get(key), dict):
            agent.update(metadata[key])
    return (
        SkillMeta(
            name=name,
            description=" ".join(description.split()),
            version=str(data.get("version") or ""),
            author=str(data.get("author") or ""),
            license=str(data.get("license") or ""),
            platforms=_strings(data.get("platforms")),
            tags=_strings(agent.get("tags") or data.get("tags")),
            category=str(agent.get("category") or ""),
            requires_toolsets=_strings(agent.get("requires_toolsets")),
            fallback_for_toolsets=_strings(agent.get("fallback_for_toolsets")),
            requires_tools=_strings(agent.get("requires_tools")),
            fallback_for_tools=_strings(agent.get("fallback_for_tools")),
            env_passthrough=_strings(agent.get("required_environment_variables") or agent.get("env_passthrough")),
            raw=data,
        ),
        body.lstrip("\n"),
    )


def parse_skill_file(path: Path) -> tuple[SkillMeta, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise SkillFormatError(f"cannot read {path}: {exc}") from exc
    return parse_skill_text(text, expected_name=path.parent.name)


def platform_matches(meta: SkillMeta, host: str | None = None) -> bool:
    """A skill with no ``platforms`` runs everywhere."""
    if not meta.platforms:
        return True
    current = host or _HOST
    aliases = {"darwin": "macos", "osx": "macos", "win32": "windows", "win": "windows"}
    return current in {aliases.get(p.lower(), p.lower()) for p in meta.platforms}


def render_skill(name: str, description: str, body: str, **extra: Any) -> str:
    """A SKILL.md document from its parts."""
    frontmatter = {"name": name, "description": description, **extra}
    return "---\n" + yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).rstrip() + "\n---\n\n" + body.strip() + "\n"
