"""Skill discovery across tiers.

Precedence, first match wins on a name clash:

1. project   ``<project root>/.clite/skills``      shared with the repository
2. local     ``<home>/skills``                      the user's own and agent-created skills
3. external  ``skills.external_dirs``               read-only directories shared between tools
4. bundled   shipped inside the package             read-only

Bundled skills are read in place. Editing one copies it into the local tier first
(copy-on-write, see ``clite.skills.manager``), so an upgrade never fights a user's edit.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clite.core.brand import PROJECT_DIRNAME
from clite.core.config import load_config
from clite.core.constants import bundled_dir, get_skills_dir, home_key
from clite.skills.frontmatter import SkillFormatError, SkillMeta, parse_skill_file, platform_matches

logger = logging.getLogger("clite.skills.catalog")

TIER_PROJECT, TIER_LOCAL, TIER_EXTERNAL, TIER_BUNDLED = "project", "local", "external", "bundled"
LINKED_DIRS = ("references", "templates", "scripts", "assets")
_MAX_DEPTH = 2  # <root>/<name>/SKILL.md or <root>/<category>/<name>/SKILL.md


@dataclass
class Skill:
    name: str
    description: str
    directory: Path
    tier: str
    category: str
    meta: SkillMeta

    @property
    def file(self) -> Path:
        return self.directory / "SKILL.md"

    @property
    def writable(self) -> bool:
        return self.tier == TIER_LOCAL

    def summary(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "category": self.category, "tier": self.tier,
                "version": self.meta.version, "tags": list(self.meta.tags)}


def find_project_root(start: str | os.PathLike[str] | None = None) -> Path | None:
    """The nearest ancestor holding ``.git``, or ``None`` outside a repository."""
    current = Path(start or os.getcwd()).resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


# Directories contributed by plugins (``ctx.register_skills_dir``), per home.
_EXTRA_ROOTS: dict[str, list[Path]] = {}


def register_extra_root(directory: Path) -> None:
    roots = _EXTRA_ROOTS.setdefault(home_key(), [])
    if directory not in roots:
        roots.append(directory)


def unregister_extra_root(directory: Path) -> None:
    roots = _EXTRA_ROOTS.get(home_key(), [])
    if directory in roots:
        roots.remove(directory)


def skill_roots(cwd: str | os.PathLike[str] | None = None, config: dict[str, Any] | None = None) -> list[tuple[str, Path]]:
    cfg = config if config is not None else load_config()
    roots: list[tuple[str, Path]] = []
    project = find_project_root(cwd)
    if project is not None:
        roots.append((TIER_PROJECT, project / PROJECT_DIRNAME / "skills"))
    roots.append((TIER_LOCAL, get_skills_dir()))
    for external in (cfg.get("skills") or {}).get("external_dirs") or []:
        roots.append((TIER_EXTERNAL, Path(os.path.expanduser(os.path.expandvars(str(external))))))
    roots.extend((TIER_EXTERNAL, directory) for directory in _EXTRA_ROOTS.get(home_key(), ()))
    roots.append((TIER_BUNDLED, bundled_dir() / "skills"))
    return roots


def _skill_files(root: Path) -> list[Path]:
    found: list[Path] = []
    if not root.is_dir():
        return found

    def walk(directory: Path, depth: int) -> None:
        try:
            children = sorted(directory.iterdir())
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.name.startswith("."):
                continue
            if (child / "SKILL.md").is_file():
                found.append(child / "SKILL.md")
            elif depth < _MAX_DEPTH:
                walk(child, depth + 1)

    walk(root, 1)
    return found


def discover_skills(
    *,
    cwd: str | os.PathLike[str] | None = None,
    config: dict[str, Any] | None = None,
    include_disabled: bool = False,
    all_platforms: bool = False,
) -> list[Skill]:
    """Every usable skill, highest tier first, sorted by category then name."""
    cfg = config if config is not None else load_config()
    disabled = set((cfg.get("skills") or {}).get("disabled") or [])
    chosen: dict[str, Skill] = {}
    for tier, root in skill_roots(cwd, cfg):
        for path in _skill_files(root):
            try:
                meta, _body = parse_skill_file(path)
            except SkillFormatError as exc:
                logger.debug("skipping %s: %s", path, exc)
                continue
            if meta.name in chosen:
                continue  # a higher tier already provides this name
            if not all_platforms and not platform_matches(meta):
                continue
            if not include_disabled and meta.name in disabled:
                continue
            relative = path.parent.relative_to(root)
            category = meta.category or (relative.parts[0] if len(relative.parts) > 1 else "")
            chosen[meta.name] = Skill(meta.name, meta.description, path.parent, tier, category, meta)
    return sorted(chosen.values(), key=lambda skill: (skill.category or "~", skill.name))


def get_skill(name: str, *, cwd: str | os.PathLike[str] | None = None, config: dict[str, Any] | None = None) -> Skill | None:
    for skill in discover_skills(cwd=cwd, config=config, include_disabled=True, all_platforms=True):
        if skill.name == name:
            return skill
    return None


def linked_files(skill: Skill) -> dict[str, list[str]]:
    """Supporting files by kind, as paths relative to the skill directory."""
    files: dict[str, list[str]] = {}
    for kind in LINKED_DIRS:
        directory = skill.directory / kind
        if directory.is_dir():
            entries = sorted(p.relative_to(skill.directory).as_posix() for p in directory.rglob("*") if p.is_file())
            if entries:
                files[kind] = entries
    return files


def read_skill_file(skill: Skill, relative_path: str | None = None) -> str:
    """SKILL.md, or a supporting file. Paths that leave the skill directory are refused."""
    if not relative_path:
        return skill.file.read_text(encoding="utf-8")
    target = (skill.directory / relative_path).resolve()
    try:
        target.relative_to(skill.directory.resolve())
    except ValueError:
        raise PermissionError(f"{relative_path!r} is outside the skill directory") from None
    if not target.is_file():
        raise FileNotFoundError(f"{relative_path!r} does not exist in skill {skill.name!r}")
    return target.read_text(encoding="utf-8", errors="replace")


def reset_skill_cache() -> None:
    """Forget plugin-contributed roots. Discovery itself is uncached: it always reads disk."""
    _EXTRA_ROOTS.clear()
