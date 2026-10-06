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
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clite import __version__
from clite.core.constants import get_skills_dir
from clite.core.env import SecretSpec, get_secret, register_secret
from clite.core.io import atomic_write_json, atomic_write_text, read_json
from clite.core.threats import describe, scan_text
from clite.skills.catalog import TIER_LOCAL, get_skill
from clite.skills.frontmatter import SkillFormatError, parse_skill_text, validate_skill_name
from clite.skills.manager import SkillError, _safe_local_path
from clite.skills.usage import record_created

MAX_BUNDLE_FILES = 200
MAX_BUNDLE_BYTES = 5_000_000
_TEXT_SUFFIXES = {".md", ".txt", ".py", ".sh", ".js", ".ts", ".json", ".yaml", ".yml", ".toml", ".html", ".css", ""}
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
# Where GitHub serves file bytes for the contents API. The token goes to these and the API host only.
_GITHUB_DOWNLOAD_HOSTS = frozenset({"raw.githubusercontent.com"})

register_secret(SecretSpec(GITHUB_TOKEN_ENV, "GitHub token: private skill repositories and a higher rate limit",
                           category="tool", url="https://github.com/settings/tokens"))


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
    """Install from ``owner/repo/path/to/skill[@ref]`` using the GitHub contents API.

    ``GITHUB_TOKEN`` in ``.env`` is used when set: private repositories, and 5000 requests an
    hour instead of 60. It is sent only to the API host and GitHub's download host.
    """

    source_id = "github"

    def __init__(self, api: str = "https://api.github.com", download_hosts: frozenset[str] = _GITHUB_DOWNLOAD_HOSTS) -> None:
        self.api = api.rstrip("/")
        self._token_hosts = {urllib.parse.urlsplit(self.api).netloc, *download_hosts}

    def _open(self, url: str, accept: str, limit: int | None = None) -> bytes:
        headers = {"User-Agent": f"clite/{__version__}", "Accept": accept}
        token = get_secret(GITHUB_TOKEN_ENV)
        if token and urllib.parse.urlsplit(url).netloc in self._token_hosts:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(url, headers=headers)  # noqa: S310 - https hosts from the API
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                return response.read() if limit is None else response.read(limit + 1)
        except urllib.error.HTTPError as exc:
            raise SkillError(self._http_error(exc, has_token=bool(token))) from None
        except (urllib.error.URLError, OSError) as exc:
            raise SkillError(f"GitHub request failed: {exc}") from None

    @staticmethod
    def _http_error(exc: urllib.error.HTTPError, *, has_token: bool) -> str:
        if exc.code in (403, 429) and exc.headers.get("X-RateLimit-Remaining") == "0":
            reset = exc.headers.get("X-RateLimit-Reset", "")
            when = time.strftime("%H:%M", time.localtime(int(reset))) if reset.isdigit() else "within the hour"
            hint = "" if has_token else f" Set {GITHUB_TOKEN_ENV} in .env for 5000 requests an hour instead of 60."
            return f"GitHub rate limit reached; it resets at {when}.{hint}"
        if exc.code == 404:
            hint = "" if has_token else f" If the repository is private, set {GITHUB_TOKEN_ENV} in .env."
            return f"not found on GitHub (check owner, repository, path and ref).{hint}"
        if exc.code == 401:
            return f"GitHub refused {GITHUB_TOKEN_ENV}: it is invalid or expired"
        return f"GitHub request failed: HTTP {exc.code}"

    def _get(self, url: str) -> Any:
        try:
            return json.loads(self._open(url, "application/vnd.github+json"))
        except ValueError as exc:
            raise SkillError(f"GitHub sent a response that is not JSON: {exc}") from None

    def fetch(self, identifier: str) -> SkillBundle:
        spec, _, ref = identifier.strip().partition("@")
        parts = spec.strip("/").split("/")
        if len(parts) < 3:
            raise SkillError("a GitHub skill identifier looks like owner/repo/path/to/skill (optionally @branch-or-tag)")
        owner, repo, path = parts[0], parts[1], "/".join(parts[2:])
        query = f"?ref={urllib.parse.quote(ref, safe='')}" if ref else ""
        files: dict[str, bytes] = {}
        total = 0

        def walk(remote: str, prefix: str) -> None:
            nonlocal total
            listing = self._get(f"{self.api}/repos/{owner}/{repo}/contents/{urllib.parse.quote(remote)}{query}")
            if not isinstance(listing, list):
                raise SkillError(f"{identifier} is not a directory in {owner}/{repo}")
            for entry in listing:
                if len(files) >= MAX_BUNDLE_FILES:
                    raise SkillError(f"skill has more than {MAX_BUNDLE_FILES} files")
                if entry.get("type") == "dir":
                    walk(entry["path"], prefix + entry["name"] + "/")
                elif entry.get("type") == "file" and entry.get("download_url"):
                    # Check the listed size first so an oversized skill is refused before downloading it.
                    total += int(entry.get("size") or 0)
                    if total > MAX_BUNDLE_BYTES:
                        raise SkillError(f"skill is larger than {MAX_BUNDLE_BYTES} bytes")
                    content = self._open(entry["download_url"], "application/octet-stream", MAX_BUNDLE_BYTES)
                    if len(content) > MAX_BUNDLE_BYTES:
                        raise SkillError(f"skill is larger than {MAX_BUNDLE_BYTES} bytes")
                    files[prefix + entry["name"]] = content

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
    if category:
        try:
            validate_skill_name(category)
        except SkillFormatError as exc:
            raise SkillError(f"invalid skill category {category!r}: {exc}") from exc
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
    # Validate every destination before replacing even the first file of an existing skill.
    targets = [(_safe_local_path(directory / path), content) for path, content in bundle.files.items()]
    for target, content in targets:
        if target.suffix.lower() in _TEXT_SUFFIXES:
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
