"""Skill installation from outside sources.

A source knows how to turn an identifier into a bundle of files. Installation is the same for
every source: validate the SKILL.md, scan every file, then write into the local tier. Nothing
from a source is executed.

Sources shipped here: a local directory, a GitHub repository path, and an index — a JSON file
listing skills by name, with the source and hash of each. The index is what ``clite skills
search`` reads, and what makes ``install <name>`` and ``update`` work without a URL. Registries
(skills.sh, ClawHub and the like) are added by subclassing :class:`SkillSource`.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clite import __version__
from clite.core.config import config_get
from clite.core.constants import bundled_dir, get_skills_dir
from clite.core.env import SecretSpec, get_secret, register_secret
from clite.core.io import atomic_write_json, atomic_write_text, read_json
from clite.skills.catalog import TIER_LOCAL, get_skill
from clite.skills.frontmatter import SkillFormatError, parse_skill_text, validate_skill_name
from clite.skills.manager import SkillError, _safe_local_path
from clite.skills.scanner import ScanReport, scan_bundle
from clite.skills.usage import record_created

MAX_BUNDLE_FILES = 200
MAX_BUNDLE_BYTES = 5_000_000
_TEXT_SUFFIXES = {
    ".md",
    ".txt",
    ".py",
    ".sh",
    ".js",
    ".ts",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".html",
    ".css",
    "",
}
GITHUB_TOKEN_ENV = "GITHUB_TOKEN"
# Where GitHub serves file bytes for the contents API. The token goes to these and the API host only.
_GITHUB_DOWNLOAD_HOSTS = frozenset({"raw.githubusercontent.com"})

register_secret(
    SecretSpec(
        GITHUB_TOKEN_ENV,
        "GitHub token: private skill repositories and a higher rate limit",
        category="tool",
        url="https://github.com/settings/tokens",
    )
)


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
        files = skill_files(directory)
        return SkillBundle(directory.name, files, self.source_id, str(directory))


class GitHubSource(SkillSource):
    """Install from ``owner/repo/path/to/skill[@ref]`` using the GitHub contents API.

    ``GITHUB_TOKEN`` in ``.env`` is used when set: private repositories, and 5000 requests an
    hour instead of 60. It is sent only to the API host and GitHub's download host.
    """

    source_id = "github"

    def __init__(
        self, api: str = "https://api.github.com", download_hosts: frozenset[str] = _GITHUB_DOWNLOAD_HOSTS
    ) -> None:
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
                body: bytes = response.read() if limit is None else response.read(limit + 1)
                return body
        except urllib.error.HTTPError as exc:
            raise SkillError(self._http_error(exc, has_token=bool(token))) from None
        except (urllib.error.URLError, OSError) as exc:
            raise SkillError(f"GitHub request failed: {exc}") from None

    @staticmethod
    def _http_error(exc: urllib.error.HTTPError, *, has_token: bool) -> str:
        if exc.code in (403, 429) and exc.headers.get("X-RateLimit-Remaining") == "0":
            reset = exc.headers.get("X-RateLimit-Reset", "")
            when = (
                time.strftime("%H:%M", time.localtime(int(reset))) if reset.isdigit() else "within the hour"
            )
            hint = (
                ""
                if has_token
                else f" Set {GITHUB_TOKEN_ENV} in .env for 5000 requests an hour instead of 60."
            )
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

    def fetch_tree(self, identifier: str) -> tuple[str, dict[str, bytes]]:
        """Download the directory ``identifier`` names. ``(name, files)``, no format check.

        The skill installer needs a ``SKILL.md``; the plugin hub needs the same walk for a
        plugin directory, so it calls this and looks for ``plugin.yaml`` itself.
        """
        spec, _, ref = identifier.strip().partition("@")
        parts = spec.strip("/").split("/")
        if len(parts) < 3:
            raise SkillError(
                "a GitHub skill identifier looks like owner/repo/path/to/skill (optionally @branch-or-tag)"
            )
        owner, repo, path = parts[0], parts[1], "/".join(parts[2:])
        query = f"?ref={urllib.parse.quote(ref, safe='')}" if ref else ""
        files: dict[str, bytes] = {}
        total = 0

        def walk(remote: str, prefix: str) -> None:
            nonlocal total
            listing = self._get(
                f"{self.api}/repos/{owner}/{repo}/contents/{urllib.parse.quote(remote)}{query}"
            )
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
        return parts[-1], files

    def fetch(self, identifier: str) -> SkillBundle:
        name, files = self.fetch_tree(identifier)
        if "SKILL.md" not in files:
            raise SkillError(f"{identifier} has no SKILL.md")
        return SkillBundle(name, files, self.source_id, identifier)


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


def install_skill(
    identifier: str,
    *,
    source: str | None = None,
    category: str | None = None,
    force: bool = False,
    on_report: Callable[[ScanReport], bool] | None = None,
) -> dict[str, Any]:
    """Fetch, validate, scan and install a skill into the local tier.

    ``identifier`` is a path, an ``owner/repo/path[@ref]``, or a bare name from the index.
    ``on_report`` sees the scan of the whole bundle before anything is written and decides
    whether to go on — that is where a surface shows the report and asks the user. A report
    with something to refuse is refused even when ``on_report`` says yes, unless ``force``
    says the user has read it and wants it anyway.
    """
    if category:
        try:
            validate_skill_name(category)
        except SkillFormatError as exc:
            raise SkillError(f"invalid skill category {category!r}: {exc}") from exc
    entry = _index_entry_for(identifier) if source is None and _looks_like_a_name(identifier) else None
    if entry is not None:
        bundle = _fetch_entry(entry)
        source = bundle.source
        chosen_name = entry["name"]
    else:
        chosen = SOURCES.get(source) if source else _pick_source(identifier)
        if chosen is None:
            raise SkillError(f"unknown skill source {source!r}; known: {sorted(SOURCES)}")
        bundle = chosen.fetch(identifier)
        chosen_name = identifier
    if sum(len(content) for content in bundle.files.values()) > MAX_BUNDLE_BYTES:
        raise SkillError(f"skill is larger than {MAX_BUNDLE_BYTES} bytes")
    for path in bundle.files:
        if Path(path).is_absolute() or ".." in Path(path).parts:
            raise SkillError(f"unsafe path in skill bundle: {path!r}")
    try:
        meta, _ = parse_skill_text(bundle.files["SKILL.md"].decode("utf-8"))
    except (SkillFormatError, UnicodeDecodeError, KeyError) as exc:
        raise SkillError(f"not a valid skill: {exc}") from exc

    report = scan_bundle(bundle.files)
    if report.blocked and not force:
        details = "; ".join(report.lines())
        raise SkillError(
            f"security scan flagged this skill ({details}). Review it, then install with --force."
        )
    if on_report is not None and not on_report(report):
        raise SkillError(f"not installed: {chosen_name} was not approved after the scan")

    existing = get_skill(meta.name)
    if existing is not None and existing.tier == TIER_LOCAL and not force:
        raise SkillError(f"skill {meta.name!r} is already installed; use --force to replace it")
    directory = get_skills_dir() / category / meta.name if category else get_skills_dir() / meta.name
    _write_bundle(directory, bundle.files)
    lock = installed_skills()
    lock[meta.name] = {
        "source": bundle.source,
        "identifier": bundle.identifier,
        "installed_at": time.time(),
        "version": meta.version,
        "hash": bundle_digest(bundle.files),
    }
    atomic_write_json(_lock_path(), lock)
    record_created(meta.name, f"hub:{bundle.source}")
    return {
        "name": meta.name,
        "path": str(directory),
        "source": bundle.source,
        "warnings": report.threats,
        "report": report,
    }


def _write_bundle(directory: Path, files: Mapping[str, bytes]) -> None:
    """Write every file, validating all destinations before replacing the first one."""
    targets = [(_safe_local_path(directory / path), content) for path, content in files.items()]
    for target, content in targets:
        if target.suffix.lower() in _TEXT_SUFFIXES:
            atomic_write_text(target, content.decode("utf-8", errors="replace"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)


def bundle_digest(files: Mapping[str, bytes]) -> str:
    """A stable digest of a bundle: paths and contents, order-independent."""
    digest = hashlib.sha256()
    for path in sorted(files):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(files[path]).digest())
    return "sha256:" + digest.hexdigest()


# Never part of a skill: hidden files (version control, editor state) and the byte caches the
# interpreter writes next to a skill's scripts when its tests run.
_IGNORED_PARTS = frozenset({"__pycache__"})


def skill_files(directory: Path) -> dict[str, bytes]:
    """The files that make up a skill directory, by path relative to it."""
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
        and not any(
            part.startswith(".") or part in _IGNORED_PARTS for part in path.relative_to(directory).parts
        )
    }


def directory_digest(directory: Path) -> str:
    """The digest of the files a skill directory holds now, as the lock would record them."""
    return bundle_digest(skill_files(directory))


# ── the index ────────────────────────────────────────────────────────────────────────────
#
# One JSON file lists skills by name, so a search does not have to walk GitHub and an install
# does not need a URL. Each entry carries enough to fetch the skill and to check what arrived:
#
#     {"version": 1, "skills": [
#       {"name": "pdf-tools", "description": "...", "category": "tools",
#        "source": "github", "identifier": "acme/skills/tools/pdf-tools",
#        "version": "1.2.0", "hash": "sha256:..."}]}
#
# ``scripts/build_skills_index.py`` writes one; the package ships its own, built from the
# bundled skills, so a fresh install can search for something on the first run.

INDEX_FILENAME = "skills-index.json"
INDEX_VERSION = 1
ENTRY_KEYS = ("name", "description", "category", "source", "identifier", "version", "hash")


def bundled_index_path() -> Path:
    """The index that ships with the package."""
    return bundled_dir() / INDEX_FILENAME


def taps_path() -> Path:
    return get_skills_dir() / ".hub" / "taps.json"


def load_taps() -> list[dict[str, str]]:
    """The extra indexes the user added, in the order they were added."""
    data = read_json(taps_path(), {})
    taps = data.get("taps") if isinstance(data, dict) else None
    return [tap for tap in taps if isinstance(tap, dict)] if isinstance(taps, list) else []


def add_tap(spec: str) -> dict[str, str]:
    """Add another index: ``owner/repo`` on GitHub, or a path or URL to an index file."""
    spec = spec.strip()
    if not spec:
        raise SkillError("a tap needs an owner/repo, a path, or a URL")
    if _looks_like_a_repo(spec):
        name = spec
        location = f"https://raw.githubusercontent.com/{spec}/HEAD/{INDEX_FILENAME}"
    else:
        name = Path(urllib.parse.urlsplit(spec).path).name or spec
        location = spec
    taps = [tap for tap in load_taps() if tap.get("name") != name]
    taps.append({"name": name, "index": location})
    atomic_write_json(taps_path(), {"taps": taps})
    return {"name": name, "index": location}


def remove_tap(name: str) -> bool:
    taps = load_taps()
    kept = [tap for tap in taps if tap.get("name") != name]
    if len(kept) == len(taps):
        return False
    atomic_write_json(taps_path(), {"taps": kept})
    return True


def index_locations() -> list[str]:
    """Where a search looks, in order: the configured index, then every tap."""
    configured = str(config_get("skills.hub.index", "") or "").strip()
    first = configured or str(bundled_index_path())
    rest = [str(tap["index"]) for tap in load_taps() if tap.get("index")]
    return [first, *(location for location in rest if location != first)]


def read_index(location: str) -> dict[str, Any]:
    """Load one index file from a path, a ``file:`` URL, or an http(s) URL."""
    if location.startswith(("http://", "https://")):
        text = _read_url(location)
    else:
        path = Path(urllib.parse.urlsplit(location).path if location.startswith("file:") else location)
        try:
            text = path.expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise SkillError(f"cannot read the skill index at {location}: {exc}") from exc
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise SkillError(f"{location} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("skills"), list):
        raise SkillError(f"{location} is not a skill index (it needs a 'skills' list)")
    return data


def _read_url(url: str) -> str:
    request = urllib.request.Request(  # noqa: S310 - the location came from config or a tap
        url, headers={"User-Agent": f"clite/{__version__}", "Accept": "application/json"}
    )
    token = get_secret(GITHUB_TOKEN_ENV)
    if token and urllib.parse.urlsplit(url).netloc in _GITHUB_DOWNLOAD_HOSTS:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
            body: bytes = response.read(MAX_BUNDLE_BYTES)
            return body.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise SkillError(f"cannot read the skill index at {url}: HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise SkillError(f"cannot read the skill index at {url}: {exc}") from exc


@dataclass
class SearchResults:
    entries: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    locations: int = 0


def search_skills(query: str, limit: int = 10) -> SearchResults:
    """Every indexed skill whose name, description or category contains ``query``.

    One unreachable tap does not hide the rest: its problem is reported instead.
    """
    needle = query.strip().lower()
    found: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    locations = index_locations()
    for location in locations:
        try:
            data = read_index(location)
        except SkillError as exc:
            problems.append(str(exc))
            continue
        for entry in data["skills"]:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            haystack = " ".join(
                str(entry.get(key, "")) for key in ("name", "description", "category")
            ).lower()
            if needle in haystack:
                found.setdefault(str(entry["name"]), {**entry, "index": location})
    ranked = sorted(
        found.values(), key=lambda item: (not str(item["name"]).lower().startswith(needle), item["name"])
    )
    return SearchResults(entries=ranked[: max(1, limit)], problems=problems, locations=len(locations))


def find_entry(name: str) -> dict[str, Any] | None:
    """The index entry for exactly this name, from the first index that has one."""
    wanted = name.strip().lower()
    for location in index_locations():
        try:
            data = read_index(location)
        except SkillError:
            continue
        for entry in data["skills"]:
            if isinstance(entry, dict) and str(entry.get("name", "")).lower() == wanted:
                return {**entry, "index": location}
    return None


def _fetch_entry(entry: dict[str, Any]) -> SkillBundle:
    """Fetch the skill an index entry names, and check the hash the index promises."""
    name = str(entry.get("name", ""))
    source = str(entry.get("source") or "github")
    chosen = SOURCES.get(source)
    if chosen is None:
        raise SkillError(f"{name}: the index names an unknown source {source!r}")
    bundle = chosen.fetch(str(entry.get("identifier") or ""))
    expected = str(entry.get("hash") or "")
    if expected and bundle_digest(bundle.files) != expected:
        raise SkillError(
            f"{name}: the download does not match the hash in the index "
            f"(expected {expected}, got {bundle_digest(bundle.files)})"
        )
    return bundle


def _looks_like_a_name(identifier: str) -> bool:
    """A bare skill name, as opposed to a path or an ``owner/repo/path``."""
    return "/" not in identifier.strip() and not Path(identifier).expanduser().exists()


def _looks_like_a_repo(spec: str) -> bool:
    return "/" in spec and len(spec.strip("/").split("/")) == 2 and "://" not in spec


def _index_entry_for(identifier: str) -> dict[str, Any] | None:
    entry = find_entry(identifier)
    if entry is None:
        known = search_skills("").entries
        hint = f" Known skills: {', '.join(str(item['name']) for item in known[:10])}." if known else ""
        raise SkillError(f"no skill named {identifier!r} in the index.{hint}")
    return entry


def build_index(root: str | Path, *, source: str = "github", identifier_prefix: str = "") -> dict[str, Any]:
    """Build an index document from a directory tree of skills, one ``SKILL.md`` per skill."""
    root_path = Path(root)
    entries: list[dict[str, Any]] = []
    for skill_md in sorted(root_path.rglob("SKILL.md")):
        directory = skill_md.parent
        relative = directory.relative_to(root_path).as_posix() if directory != root_path else ""
        files = skill_files(directory)
        try:
            meta, _ = parse_skill_text(files["SKILL.md"].decode("utf-8"))
        except (SkillFormatError, UnicodeDecodeError, KeyError) as exc:
            raise SkillError(f"{directory}: not a valid skill: {exc}") from exc
        identifier = f"{identifier_prefix.strip('/')}/{relative}" if identifier_prefix else str(directory)
        folder = relative.split("/")[0] if "/" in relative else ""
        entries.append(
            {
                "name": meta.name,
                "description": meta.description,
                "category": meta.category or folder,
                "source": source,
                "identifier": identifier,
                "version": meta.version,
                "hash": bundle_digest(files),
            }
        )
    names = [entry["name"] for entry in entries]
    if len(set(names)) != len(names):
        duplicated = sorted({name for name in names if names.count(name) > 1})
        raise SkillError(f"the index would have duplicate names: {', '.join(duplicated)}")
    return {"version": INDEX_VERSION, "skills": entries}


# ── updates ──────────────────────────────────────────────────────────────────────────────


@dataclass
class UpdatePlan:
    """What an update would do, worked out before anything is written."""

    name: str
    directory: Path
    bundle: SkillBundle
    changed: dict[str, str]  # path -> "added" | "removed" | "changed"
    edited_locally: bool
    report: ScanReport

    @property
    def up_to_date(self) -> bool:
        return not self.changed

    def summary(self) -> str:
        if self.up_to_date:
            return f"{self.name}: up to date"
        parts = [f"{count} {status}" for status, count in _count_by_status(self.changed).items()]
        note = " (edited locally)" if self.edited_locally else ""
        return f"{self.name}: {', '.join(parts)}{note}"


def _count_by_status(changed: Mapping[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in changed.values():
        counts[status] = counts.get(status, 0) + 1
    return {status: counts[status] for status in ("added", "removed", "changed") if status in counts}


def _diff(local: Mapping[str, bytes], incoming: Mapping[str, bytes]) -> dict[str, str]:
    changed = {}
    for path in sorted(set(local) | set(incoming)):
        if path not in local:
            changed[path] = "added"
        elif path not in incoming:
            changed[path] = "removed"
        elif local[path] != incoming[path]:
            changed[path] = "changed"
    return changed


def plan_update(name: str) -> UpdatePlan:
    """Fetch the current version of an installed skill and compare it with what is on disk."""
    record = installed_skills().get(name)
    if record is None:
        raise SkillError(f"{name!r} was not installed from a hub; there is nothing to update")
    source = str(record.get("source") or "")
    chosen = SOURCES.get(source)
    if chosen is None:
        raise SkillError(f"{name}: the lock names an unknown source {source!r}")
    directory = get_skills_dir() / name
    if not directory.is_dir():
        directory = _find_installed_dir(name) or directory
    bundle = chosen.fetch(str(record.get("identifier") or ""))
    report = scan_bundle(bundle.files)
    local = skill_files(directory)
    recorded = str(record.get("hash") or "")
    edited_locally = bool(recorded) and directory_digest(directory) != recorded
    return UpdatePlan(
        name=name,
        directory=directory,
        bundle=bundle,
        changed=_diff(local, bundle.files),
        edited_locally=edited_locally,
        report=report,
    )


def _find_installed_dir(name: str) -> Path | None:
    skill = get_skill(name)
    return skill.directory if skill is not None else None


def apply_update(plan: UpdatePlan, *, force: bool = False) -> dict[str, Any]:
    """Write the fetched bundle over the installed skill.

    Refuses when the local copy is not what the hub installed, unless ``force`` says the user
    has seen the diff and still wants the hub's version. Edits are never merged.
    """
    if plan.report.blocked and not force:
        raise SkillError(
            f"security scan flagged {plan.name} ({'; '.join(plan.report.lines())}); "
            "review it, then update with --force"
        )
    if plan.edited_locally and not force:
        raise SkillError(
            f"{plan.name} was edited since it was installed; update it with --force to "
            "replace your changes, or copy them aside first"
        )
    if plan.up_to_date:
        return {"name": plan.name, "changed": {}, "updated": False}
    _write_bundle(plan.directory, plan.bundle.files)
    lock = installed_skills()
    record = dict(lock.get(plan.name) or {})
    record.update(
        source=plan.bundle.source,
        identifier=plan.bundle.identifier,
        installed_at=time.time(),
        version=_bundle_version(plan.bundle),
        hash=bundle_digest(plan.bundle.files),
    )
    lock[plan.name] = record
    atomic_write_json(_lock_path(), lock)
    return {"name": plan.name, "changed": plan.changed, "updated": True}


def _bundle_version(bundle: SkillBundle) -> str:
    try:
        meta, _ = parse_skill_text(bundle.files["SKILL.md"].decode("utf-8"))
    except (SkillFormatError, UnicodeDecodeError, KeyError):
        return ""
    return meta.version
