"""Skill installation from outside sources.

A source knows how to turn an identifier into a bundle of files. Installation is the same for
every source: validate the SKILL.md, scan every text file, then write into the local tier.
Nothing from a source is executed.

Sources shipped here: a local directory, and a GitHub repository path. Registries
(skills.sh, ClawHub and the like) are added by subclassing :class:`SkillSource`.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clite import __version__
from clite.core.constants import get_skills_dir
from clite.core.io import atomic_write_json, atomic_write_text, read_json
from clite.core.threats import describe, scan_text
from clite.skills.catalog import TIER_LOCAL, get_skill
from clite.skills.frontmatter import SkillFormatError, parse_skill_text
from clite.skills.manager import SkillError
from clite.skills.usage import record_created

MAX_BUNDLE_FILES = 200
MAX_BUNDLE_BYTES = 5_000_000
_TEXT_SUFFIXES = {".md", ".txt", ".py", ".sh", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".html", ".css", ""}


@dataclass
class SkillBundle:
    name: str
    files: dict[str, bytes]  # path relative to the skill directory -> content
    source: str
    identifier: str
    metadata: dict[str, Any] = field(default_factory=dict)


class SkillSource(ABC):
    source_id = ""

    @abstractmethod
    def fetch(self, identifier: str) -> SkillBundle:
        """Download the skill named by ``identifier``. Raise ``SkillError`` when it cannot."""

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        return []


class LocalDirSource(SkillSource):
    """Install from a directory on disk: ``clite skills install ./my-skill``."""

    source_id = "local"

    def fetch(self, identifier: str) -> SkillBundle:
        directory = Path(identifier).expanduser().resolve()
        if not (directory / "SKILL.md").is_file():
            raise SkillError(f"{directory} has no SKILL.md")
        files = {
            path.relative_to(directory).as_posix(): path.read_bytes()
            for path in sorted(directory.rglob("*"))
            if path.is_file() and not any(part.startswith(".") for part in path.relative_to(directory).parts)
        }
        return SkillBundle(directory.name, files, self.source_id, str(directory))


class GitHubSource(SkillSource):
    """Install from ``owner/repo/path/to/skill`` using the GitHub contents API."""

    source_id = "github"
    api = "https://api.github.com"

    def _get(self, url: str) -> Any:
        request = urllib.request.Request(url, headers={  # noqa: S310 - fixed https host
            "User-Agent": f"clite/{__version__}", "Accept": "application/vnd.github+json"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                return json.loads(response.read())
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise SkillError(f"GitHub request failed: {exc}") from exc

    def _download(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": f"clite/{__version__}"})  # noqa: S310
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            return response.read(MAX_BUNDLE_BYTES + 1)

    def fetch(self, identifier: str) -> SkillBundle:
        parts = identifier.strip("/").split("/")
        if len(parts) < 3:
            raise SkillError("a GitHub skill identifier looks like owner/repo/path/to/skill")
        owner, repo, path = parts[0], parts[1], "/".join(parts[2:])
        files: dict[str, bytes] = {}

        def walk(remote: str, prefix: str) -> None:
            listing = self._get(f"{self.api}/repos/{owner}/{repo}/contents/{remote}")
            if not isinstance(listing, list):
                raise SkillError(f"{identifier} is not a directory in {owner}/{repo}")
            for entry in listing:
                if len(files) >= MAX_BUNDLE_FILES:
                    raise SkillError(f"skill has more than {MAX_BUNDLE_FILES} files")
                if entry.get("type") == "dir":
                    walk(entry["path"], prefix + entry["name"] + "/")
                elif entry.get("type") == "file" and entry.get("download_url"):
                    files[prefix + entry["name"]] = self._download(entry["download_url"])

        walk(path, "")
        if "SKILL.md" not in files:
            raise SkillError(f"{identifier} has no SKILL.md")
        return SkillBundle(parts[-1], files, self.source_id, identifier)


SOURCES: dict[str, SkillSource] = {"local": LocalDirSource(), "github": GitHubSource()}


def register_skill_source(source: SkillSource) -> None:
    SOURCES[source.source_id] = source


def _lock_path() -> Path:
    return get_skills_dir() / ".hub" / "lock.json"


def installed_skills() -> dict[str, dict[str, Any]]:
    data = read_json(_lock_path(), {})
    return data if isinstance(data, dict) else {}


def _pick_source(identifier: str) -> SkillSource:
    if identifier.startswith(("./", "/", "~", "..")) or Path(identifier).expanduser().is_dir():
        return SOURCES["local"]
    return SOURCES["github"]


def install_skill(identifier: str, *, source: str | None = None, category: str | None = None,
                  force: bool = False) -> dict[str, Any]:
    """Fetch, validate, scan and install a skill into the local tier."""
    chosen = SOURCES.get(source) if source else _pick_source(identifier)
    if chosen is None:
        raise SkillError(f"unknown skill source {source!r}; known: {sorted(SOURCES)}")
    bundle = chosen.fetch(identifier)
    if sum(len(content) for content in bundle.files.values()) > MAX_BUNDLE_BYTES:
        raise SkillError(f"skill is larger than {MAX_BUNDLE_BYTES} bytes")
    try:
        meta, _ = parse_skill_text(bundle.files["SKILL.md"].decode("utf-8"))
    except (SkillFormatError, UnicodeDecodeError, KeyError) as exc:
        raise SkillError(f"not a valid skill: {exc}") from exc

    findings: dict[str, str] = {}
    for path, content in bundle.files.items():
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise SkillError(f"unsafe path in skill bundle: {path!r}")
        if Path(path).suffix.lower() in _TEXT_SUFFIXES:
            threats = scan_text(content.decode("utf-8", errors="replace"))
            if threats:
                findings[path] = describe(threats)
    if findings and not force:
        details = "; ".join(f"{path}: {what}" for path, what in findings.items())
        raise SkillError(f"security scan flagged this skill ({details}). Review it, then install with --force.")

    existing = get_skill(meta.name)
    if existing is not None and existing.tier == TIER_LOCAL and not force:
        raise SkillError(f"skill {meta.name!r} is already installed; use --force to replace it")
    directory = get_skills_dir() / category / meta.name if category else get_skills_dir() / meta.name
    for path, content in bundle.files.items():
        target = directory / path
        if Path(path).suffix.lower() in _TEXT_SUFFIXES:
            atomic_write_text(target, content.decode("utf-8", errors="replace"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    lock = installed_skills()
    lock[meta.name] = {"source": bundle.source, "identifier": bundle.identifier, "installed_at": time.time(),
                       "version": meta.version}
    atomic_write_json(_lock_path(), lock)
    record_created(meta.name, f"hub:{bundle.source}")
    return {"name": meta.name, "path": str(directory), "source": bundle.source, "warnings": findings}
