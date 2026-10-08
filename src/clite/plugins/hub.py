"""The plugin hub: where a plugin came from, how it is updated, and where it is found.

Installing never enables anything, and updating does not quietly turn a plugin back on: after
an update the plugin is **disabled** until the user enables it again. Two other rules from
``docs/arsitektur/06-keamanan.md`` live here too — a plugin's ``pip_dependencies`` are printed
as a command for the user to run (nothing is installed for them), and an update never writes
over a plugin the user has edited unless they say so.

The catalog is one JSON file listing plugins by name, the same idea as the skill hub index:
``scripts/build_plugins_index.py`` writes one, and the package ships one built from the bundled
plugins, so ``clite plugins search`` has something to answer with on a fresh install.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clite import __version__
from clite.core.config import config_get
from clite.core.constants import bundled_dir, ensure_dir, get_plugins_dir
from clite.core.io import atomic_write_json, read_json
from clite.plugins.manifest import RESERVED_DIRS, PluginManifest, load_manifest
from clite.skills.hub import GitHubSource, bundle_digest

SOURCE_LOCAL, SOURCE_GIT, SOURCE_GITHUB = "local", "git", "github"
PROVENANCE_FILENAME = "provenance.json"
INDEX_FILENAME = "plugins-index.json"
INDEX_VERSION = 1
_GITHUB = GitHubSource()
# Never part of a plugin: version control metadata, and byte caches the interpreter writes.
_IGNORED_PARTS = frozenset({"__pycache__", ".git"})


class PluginError(ValueError):
    """The hub could not do what was asked. The message is meant for the user."""


# ── provenance ───────────────────────────────────────────────────────────────────────────


def hub_dir() -> Path:
    return get_plugins_dir() / ".hub"


def provenance_path() -> Path:
    return hub_dir() / PROVENANCE_FILENAME


def installed_plugins() -> dict[str, dict[str, Any]]:
    """Where each installed plugin came from, as recorded at install time."""
    data = read_json(provenance_path(), {})
    return data if isinstance(data, dict) else {}


def plugin_files(directory: Path) -> dict[str, bytes]:
    """The files a plugin directory holds, as the digest and the diff see them."""
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in sorted(directory.rglob("*"))
        if path.is_file()
        and not any(
            part in _IGNORED_PARTS or part.startswith(".") for part in path.relative_to(directory).parts
        )
    }


def plugin_digest(directory: Path) -> str:
    """A stable digest of a plugin directory's contents."""
    return bundle_digest(plugin_files(directory))


def git_commit(directory: Path) -> str:
    """The commit a checkout sits at, or ``""`` when it is not a git checkout."""
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "HEAD"],  # noqa: S603, S607
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def record_install(
    name: str, *, source: str, identifier: str, version: str = "", commit: str = "", ref: str = ""
) -> dict[str, Any]:
    """Remember what was installed and from where, so an update can ask the same source."""
    lock = installed_plugins()
    record = {
        "name": name,
        "source": source,
        "identifier": identifier,
        "ref": ref,
        "commit": commit,
        "version": version,
        "installed_at": time.time(),
        "hash": plugin_digest(get_plugins_dir() / name),
    }
    lock[name] = record
    atomic_write_json(provenance_path(), lock)
    return record


def dependency_commands(manifest: PluginManifest) -> list[str]:
    """The command the user must run for ``pip_dependencies``. Nothing is installed for them."""
    if not manifest.pip_dependencies:
        return []
    return ["pip install " + " ".join(manifest.pip_dependencies)]


# ── staging a source ─────────────────────────────────────────────────────────────────────


@dataclass
class Staged:
    """A plugin source downloaded into a scratch directory, not yet in place."""

    manifest: PluginManifest
    directory: Path
    source: str
    identifier: str
    commit: str = ""
    ref: str = ""


def _staging(name: str) -> Path:
    root = ensure_dir(hub_dir() / "staging")
    target = root / name
    shutil.rmtree(target, ignore_errors=True)
    return target


def write_tree(directory: Path, files: Mapping[str, bytes]) -> None:
    """Write a downloaded bundle into ``directory``, refusing paths that escape it."""
    root = directory.resolve()
    for relative, content in files.items():
        path = Path(relative)
        target = (root / path).resolve()
        if path.is_absolute() or ".." in path.parts or root not in target.parents:
            raise PluginError(f"unsafe path in a plugin bundle: {relative!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def stage(source: str, *, ref: str = "") -> Staged:
    """Fetch ``source`` into a scratch directory and read its manifest.

    A source is a directory path, a git URL, or a name from the catalog.
    """
    expanded = Path(source).expanduser()
    if expanded.is_dir():
        if not (expanded / "plugin.yaml").is_file():
            raise PluginError(f"{expanded} has no plugin.yaml")
        identifier = str(expanded.resolve())
        directory = _staging(expanded.name)
        shutil.copytree(expanded, directory, ignore=shutil.ignore_patterns(".git", "__pycache__"))
        return Staged(
            load_manifest(directory),
            directory,
            SOURCE_LOCAL,
            identifier,
            commit=git_commit(expanded),
        )
    if source.startswith(("https://", "git@", "ssh://")) or source.endswith(".git"):
        directory = _staging(Path(source.rstrip("/")).name.removesuffix(".git") or "plugin")
        command = ["git", "clone", "--depth", "1"]  # noqa: S607 - git is the documented tool
        if ref:
            command += ["--branch", ref]
        command += [source, str(directory)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
        if result.returncode != 0:
            raise PluginError(f"git clone failed: {result.stderr.strip()[:300]}")
        commit = git_commit(directory)
        shutil.rmtree(directory / ".git", ignore_errors=True)
        return Staged(load_manifest(directory), directory, SOURCE_GIT, source, commit=commit, ref=ref)
    entry = find_entry(source)
    if entry is None:
        known = search_plugins("").entries
        hint = f" Known plugins: {', '.join(str(item['name']) for item in known[:10])}." if known else ""
        raise PluginError(f"no plugin named {source!r} in the catalog.{hint}")
    return stage_entry(entry)


def stage_entry(entry: Mapping[str, Any]) -> Staged:
    """Stage a catalog entry, checking the download against the hash the index promises."""
    name = str(entry.get("name") or "")
    kind = str(entry.get("source") or SOURCE_GITHUB)
    identifier = str(entry.get("identifier") or "")
    if kind == SOURCE_LOCAL:
        staged = stage(identifier)
    elif kind == SOURCE_GITHUB:
        directory = _staging(name or "plugin")
        try:
            _, files = _GITHUB.fetch_tree(identifier)
            write_tree(directory, files)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        staged = Staged(load_manifest(directory), directory, SOURCE_GITHUB, identifier)
    else:
        raise PluginError(f"{name}: the catalog names an unknown source {kind!r}")
    expected = str(entry.get("hash") or "")
    actual = plugin_digest(staged.directory)
    if expected and actual != expected:
        shutil.rmtree(staged.directory, ignore_errors=True)
        raise PluginError(
            f"{name}: the download does not match the hash in the catalog (expected {expected}, got {actual})"
        )
    return staged


# ── updates ──────────────────────────────────────────────────────────────────────────────


@dataclass
class UpdatePlan:
    """What an update would do, worked out before anything is written."""

    name: str
    record: dict[str, Any]
    staged: Staged
    changed: dict[str, str]  # path -> "added" | "removed" | "changed"
    edited_locally: bool

    @property
    def up_to_date(self) -> bool:
        return not self.changed

    @property
    def commit(self) -> str:
        return self.staged.commit or str(self.record.get("commit") or "")

    def summary(self) -> str:
        if self.up_to_date:
            return f"{self.name}: up to date"
        parts = [f"{count} {status}" for status, count in _count_by_status(self.changed).items()]
        note = " (edited locally)" if self.edited_locally else ""
        return f"{self.name}: {', '.join(parts)}{note}"

    def lines(self) -> list[str]:
        """One line per changed file, so a user can see what an update brings."""
        return [f"  {status:<8} {path}" for path, status in sorted(self.changed.items())]


def _count_by_status(changed: Mapping[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for status in changed.values():
        counts[status] = counts.get(status, 0) + 1
    return {status: counts[status] for status in ("added", "removed", "changed") if status in counts}


def _diff(local: Mapping[str, bytes], incoming: Mapping[str, bytes]) -> dict[str, str]:
    changed: dict[str, str] = {}
    for path in sorted(set(local) | set(incoming)):
        if path not in local:
            changed[path] = "added"
        elif path not in incoming:
            changed[path] = "removed"
        elif local[path] != incoming[path]:
            changed[path] = "changed"
    return changed


def plan_update(name: str) -> UpdatePlan:
    """Fetch the current version of an installed plugin and compare it with what is on disk."""
    record = installed_plugins().get(name)
    if record is None:
        raise PluginError(f"{name!r} was not installed from a source, so there is nothing to update")
    directory = get_plugins_dir() / name
    if not (directory / "plugin.yaml").is_file():
        raise PluginError(f"{name} is not installed at {directory}")
    try:
        staged = stage(str(record.get("identifier") or ""), ref=str(record.get("ref") or ""))
        if staged.manifest.name != name:
            raise PluginError(f"the source now calls itself {staged.manifest.name!r}; expected {name!r}")
        recorded = str(record.get("hash") or "")
        return UpdatePlan(
            name=name,
            record=record,
            staged=staged,
            changed=_diff(plugin_files(directory), plugin_files(staged.directory)),
            edited_locally=bool(recorded) and plugin_digest(directory) != recorded,
        )
    except Exception:
        shutil.rmtree(_staging(name), ignore_errors=True)
        raise


def apply_update(plan: UpdatePlan, *, force: bool = False) -> dict[str, Any]:
    """Put the staged version in place, then leave the plugin disabled.

    Refuses to overwrite a plugin that changed since it was installed, unless ``force`` says
    the user has read the diff and wants the source's version. Edits are never merged.
    """
    from clite.plugins.manager import get_plugin_manager, set_plugin_enabled

    if plan.up_to_date:
        shutil.rmtree(plan.staged.directory, ignore_errors=True)
        return {"name": plan.name, "changed": {}, "updated": False}
    if plan.edited_locally and not force:
        raise PluginError(
            f"{plan.name} was edited since it was installed; update it with --force to replace "
            "your changes, or copy them aside first"
        )
    target = get_plugins_dir() / plan.name
    previous = plan.staged.directory.with_name(f"{plan.name}.previous")
    shutil.rmtree(previous, ignore_errors=True)
    get_plugin_manager().unload(plan.name)
    target.rename(previous)
    try:
        plan.staged.directory.rename(target)
    except Exception:
        previous.rename(target)  # put the old plugin back rather than leave a hole
        raise
    shutil.rmtree(previous, ignore_errors=True)
    record_install(
        plan.name,
        source=plan.staged.source,
        identifier=plan.staged.identifier,
        version=plan.staged.manifest.version,
        commit=plan.staged.commit or str(plan.record.get("commit") or ""),
        ref=plan.staged.ref or str(plan.record.get("ref") or ""),
    )
    # An updated plugin never comes back on by itself: the new code has not been read yet.
    set_plugin_enabled(plan.name, False)
    return {"name": plan.name, "changed": plan.changed, "updated": True}


# ── the catalog ──────────────────────────────────────────────────────────────────────────
#
# One JSON file lists plugins by name, so a search does not have to walk GitHub and an install
# does not need a URL:
#
#     {"version": 1, "plugins": [
#       {"name": "audit-log", "description": "...", "version": "1.0.0", "kind": "standalone",
#        "source": "github", "identifier": "acme/plugins/audit-log", "hash": "sha256:..."}]}


def bundled_index_path() -> Path:
    """The catalog that ships with the package."""
    return bundled_dir() / INDEX_FILENAME


def index_locations() -> list[str]:
    """Where a search looks: ``plugins.hub.index``, or the bundled catalog when it is empty."""
    configured = str(config_get("plugins.hub.index", "") or "").strip()
    return [configured or str(bundled_index_path())]


def read_index(location: str) -> dict[str, Any]:
    """Load one catalog from a path, a ``file:`` URL, or an http(s) URL."""
    if location.startswith(("http://", "https://")):
        request = urllib.request.Request(  # noqa: S310 - the location came from config
            location, headers={"User-Agent": f"clite/{__version__}", "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:  # noqa: S310
                text = response.read(5_000_000).decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError) as exc:
            raise PluginError(f"cannot read the plugin catalog at {location}: {exc}") from None
    else:
        path = Path(urllib.parse.urlsplit(location).path if location.startswith("file:") else location)
        try:
            text = path.expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise PluginError(f"cannot read the plugin catalog at {location}: {exc}") from None
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise PluginError(f"{location} is not valid JSON: {exc}") from None
    if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
        raise PluginError(f"{location} is not a plugin catalog (it needs a 'plugins' list)")
    return data


@dataclass
class SearchResults:
    entries: list[dict[str, Any]] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    locations: int = 0


def search_plugins(query: str, limit: int = 10) -> SearchResults:
    """Every cataloged plugin whose name, description or kind contains ``query``."""
    needle = query.strip().lower()
    found: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    locations = index_locations()
    for location in locations:
        try:
            data = read_index(location)
        except PluginError as exc:
            problems.append(str(exc))
            continue
        for entry in data["plugins"]:
            if not isinstance(entry, dict) or not entry.get("name"):
                continue
            haystack = " ".join(
                str(entry.get(key, "")) for key in ("name", "description", "kind", "category")
            ).lower()
            if needle in haystack:
                found.setdefault(str(entry["name"]), {**entry, "index": location})
    ranked = sorted(
        found.values(), key=lambda item: (not str(item["name"]).lower().startswith(needle), item["name"])
    )
    return SearchResults(entries=ranked[: max(1, limit)], problems=problems, locations=len(locations))


def find_entry(name: str) -> dict[str, Any] | None:
    """The catalog entry for exactly this name, from the first catalog that has one."""
    wanted = name.strip().lower()
    for location in index_locations():
        try:
            data = read_index(location)
        except PluginError:
            continue
        for entry in data["plugins"]:
            if isinstance(entry, dict) and str(entry.get("name", "")).lower() == wanted:
                return {**entry, "index": location}
    return None


def build_index(
    root: str | Path, *, source: str = SOURCE_GITHUB, identifier_prefix: str = ""
) -> dict[str, Any]:
    """Build a catalog document from a directory tree, one ``plugin.yaml`` per plugin."""
    root_path = Path(root)
    entries: list[dict[str, Any]] = []
    for manifest_path in sorted(root_path.rglob("plugin.yaml")):
        if any(part in RESERVED_DIRS for part in manifest_path.relative_to(root_path).parts):
            continue  # provider profiles are not plugins (see clite.plugins.manager)
        directory = manifest_path.parent
        relative = directory.relative_to(root_path).as_posix() if directory != root_path else ""
        manifest = load_manifest(directory)
        identifier = f"{identifier_prefix.strip('/')}/{relative}" if identifier_prefix else str(directory)
        entries.append(
            {
                "name": manifest.name,
                "description": manifest.description,
                "version": manifest.version,
                "kind": manifest.kind,
                "source": source,
                "identifier": identifier,
                "hash": plugin_digest(directory),
            }
        )
    names = [entry["name"] for entry in entries]
    if len(set(names)) != len(names):
        duplicated = sorted({name for name in names if names.count(name) > 1})
        raise PluginError(f"the catalog would have duplicate names: {', '.join(duplicated)}")
    return {"version": INDEX_VERSION, "plugins": entries}
