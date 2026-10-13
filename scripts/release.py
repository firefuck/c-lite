#!/usr/bin/env python3
"""Cut a release: one version number, a checked wheel and sdist, and a local tag.

    python scripts/release.py check [--tag v0.1.0]   versions, changelog and tag agree
    python scripts/release.py bump patch|minor|major|X.Y.Z
    python scripts/release.py build                  wheel + sdist in dist/, wheel contents checked
    python scripts/release.py notes                  this version's CHANGELOG section (release body)
    python scripts/release.py tag                    annotated tag v<version> on a clean HEAD

The version is decided in one place, ``__version__`` in ``src/<package>/__init__.py``.
``pyproject.toml`` reads it from there (``[tool.setuptools.dynamic]``), ``clite --version``
prints it, and the tag is ``v`` followed by it. npm cannot read it, so ``bump`` also writes it
into each Node workspace's ``package.json`` (the desktop installer is named after it) and into
their entries in ``package-lock.json``; ``check`` fails when any of them disagree.
Publishing happens in ``.github/workflows/release.yml`` when a tag is pushed: it builds,
tests the wheel in a clean environment, then attaches wheel and sdist to a GitHub Release.
This script never pushes and never publishes.

Names are read from the repository (``core/brand.py`` and ``pyproject.toml``), so the script
keeps working after ``scripts/rename_project.py``.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
VERSION_LINE = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)
# Instructions for whoever edits the source; they are not part of the installed program.
NOT_SHIPPED = ("AGENTS.md",)


class ReleaseError(Exception):
    pass


def package_name(root: Path) -> str:
    found = sorted((root / "src").glob("*/core/brand.py"))
    if len(found) != 1:
        raise ReleaseError(
            f"expected exactly one src/<package>/core/brand.py under {root}, found {len(found)}"
        )
    return found[0].parent.parent.name


def display_name(root: Path) -> str:
    text = (root / "src" / package_name(root) / "core" / "brand.py").read_text(encoding="utf-8")
    match = re.search(r'^DISPLAY_NAME = "([^"]+)"', text, re.MULTILINE)
    if not match:
        raise ReleaseError("core/brand.py does not define DISPLAY_NAME as a plain string")
    return match.group(1)


def version_file(root: Path) -> Path:
    return root / "src" / package_name(root) / "__init__.py"


def current_version(root: Path) -> str:
    match = VERSION_LINE.search(version_file(root).read_text(encoding="utf-8"))
    if not match:
        raise ReleaseError(f'{version_file(root).relative_to(root)} has no line __version__ = "X.Y.Z"')
    return match.group(1)


def tag_for(version: str) -> str:
    return f"v{version}"


def changelog_section(root: Path, version: str) -> str:
    """The body under ``## [version]`` in CHANGELOG.md, without the heading."""
    path = root / "CHANGELOG.md"
    if not path.is_file():
        raise ReleaseError("CHANGELOG.md is missing")
    text = path.read_text(encoding="utf-8")
    heading = re.search(rf"^## \[{re.escape(version)}\][^\n]*\n", text, re.MULTILINE)
    if not heading:
        raise ReleaseError(f"CHANGELOG.md has no '## [{version}]' section. Describe the release there first.")
    following = re.search(r"^## ", text[heading.end() :], re.MULTILINE)
    body = text[heading.end() : heading.end() + following.start() if following else len(text)].strip()
    if not body:
        raise ReleaseError(f"the CHANGELOG.md section for {version} is empty")
    return body


def check(root: Path, tag: str | None = None) -> list[str]:
    """Every way the version, the build configuration, the changelog and the tag disagree."""
    problems = []
    version = current_version(root)
    if not SEMVER.match(version):
        problems.append(f"version {version!r} is not X.Y.Z")
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    declared = project.get("project", {})
    if "version" in declared:
        problems.append('pyproject.toml spells the version; it must read it: dynamic = ["version"]')
    if "version" not in declared.get("dynamic", []):
        problems.append('pyproject.toml does not list "version" under [project] dynamic')
    attr = project.get("tool", {}).get("setuptools", {}).get("dynamic", {}).get("version", {}).get("attr")
    if attr != f"{package_name(root)}.__version__":
        problems.append(
            f'[tool.setuptools.dynamic] version must be {{attr = "{package_name(root)}.__version__"}}, '
            f"found {attr!r}"
        )
    try:
        changelog_section(root, version)
    except ReleaseError as exc:
        problems.append(str(exc))
    for name in node_workspaces(root):
        declared_version = json.loads((root / name / "package.json").read_text(encoding="utf-8")).get(
            "version"
        )
        if declared_version != version:
            problems.append(f"{name}/package.json has version {declared_version!r}, expected {version!r}")
    if tag is not None and tag != tag_for(version):
        problems.append(f"tag {tag} does not match version {version}: expected {tag_for(version)}")
    return problems


def node_workspaces(root: Path) -> list[str]:
    """The Node workspaces listed in the root ``package.json``; none without one."""
    manifest = root / "package.json"
    if not manifest.is_file():
        return []
    workspaces: list[str] = json.loads(manifest.read_text(encoding="utf-8")).get("workspaces", [])
    return workspaces


def _write_json(path: Path, data: object) -> None:
    # The layout npm itself writes, so `npm install` leaves the files as they are.
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_node_versions(root: Path, version: str) -> None:
    workspaces = node_workspaces(root)
    for name in workspaces:
        manifest = root / name / "package.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        data["version"] = version
        _write_json(manifest, data)
    lockfile = root / "package-lock.json"
    if workspaces and lockfile.is_file():
        lock = json.loads(lockfile.read_text(encoding="utf-8"))
        for name in workspaces:
            entry = lock.get("packages", {}).get(name)
            if entry is not None:
                entry["version"] = version
        _write_json(lockfile, lock)


def bump(root: Path, part: str) -> str:
    """Write the next version where it is kept (see the module docstring) and return it."""
    old = current_version(root)
    if SEMVER.match(part):
        new = part
    else:
        parsed = SEMVER.match(old)
        if not parsed:
            raise ReleaseError(f"current version {old!r} is not X.Y.Z; give the new version explicitly")
        major, minor, patch = (int(number) for number in parsed.groups())
        if part == "major":
            new = f"{major + 1}.0.0"
        elif part == "minor":
            new = f"{major}.{minor + 1}.0"
        elif part == "patch":
            new = f"{major}.{minor}.{patch + 1}"
        else:
            raise ReleaseError(f"unknown bump {part!r}: use major, minor, patch or X.Y.Z")
    path = version_file(root)
    path.write_text(
        VERSION_LINE.sub(f'__version__ = "{new}"', path.read_text(encoding="utf-8"), count=1),
        encoding="utf-8",
    )
    _write_node_versions(root, new)
    return new


def expected_wheel_files(root: Path) -> set[str]:
    """Paths (inside the wheel) of every file the package directory ships."""
    package = root / "src" / package_name(root)
    expected = set()
    for path in package.rglob("*"):
        relative = path.relative_to(root / "src")
        if (
            not path.is_file()
            or "__pycache__" in relative.parts
            or path.suffix in (".pyc", ".pyo")
            or path.name in NOT_SHIPPED
        ):
            continue
        expected.add(relative.as_posix())
    return expected


def inspect_wheel(wheel: Path, root: Path) -> list[str]:
    """What is wrong with ``wheel``: missing package files, metadata, licence or entry point."""
    package = package_name(root)
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        dist_info = sorted(
            {name.split("/", 1)[0] for name in names if name.split("/", 1)[0].endswith(".dist-info")}
        )
        if len(dist_info) != 1:
            return [f"expected one .dist-info directory in {wheel.name}, found {dist_info}"]
        metadata = archive.read(f"{dist_info[0]}/METADATA").decode("utf-8")
        entry_points = (
            archive.read(f"{dist_info[0]}/entry_points.txt").decode("utf-8")
            if f"{dist_info[0]}/entry_points.txt" in names
            else ""
        )
    problems = [f"missing from the wheel: {name}" for name in sorted(expected_wheel_files(root) - names)]
    leaked = sorted(name for name in names if name.endswith((".pyc", "/AGENTS.md")))
    problems += [f"should not be in the wheel: {name}" for name in leaked]
    distribution = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["name"]
    version = current_version(root)
    if f"\nName: {distribution}\n" not in metadata:
        problems.append(f"METADATA does not name the distribution {distribution!r}")
    if f"\nVersion: {version}\n" not in metadata:
        problems.append(f"METADATA does not carry version {version}")
    if not any(name.startswith(f"{dist_info[0]}/licenses/LICENSE") for name in names):
        problems.append("the LICENSE file is not in the wheel")
    if not re.search(
        rf"^{re.escape(package)} = {re.escape(package)}\.cli\.main:main$", entry_points, re.MULTILINE
    ):
        problems.append(f"the wheel does not install the {package!r} command")
    return problems


def build(root: Path) -> list[Path]:
    """Build wheel and sdist into a fresh ``dist/`` and check the wheel."""
    dist = root / "dist"
    shutil.rmtree(dist, ignore_errors=True)
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(dist), str(root)],
        cwd=root,
        timeout=900,
    )
    if result.returncode:
        raise ReleaseError("the build failed (needs the `build` package: pip install 'build>=1.2,<2')")
    wheels, sdists = sorted(dist.glob("*.whl")), sorted(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ReleaseError(
            f"expected one wheel and one sdist in dist/, found {[path.name for path in dist.iterdir()]}"
        )
    problems = inspect_wheel(wheels[0], root)
    if problems:
        raise ReleaseError("the wheel is incomplete:\n  " + "\n  ".join(problems))
    return [wheels[0], sdists[0]]


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60)  # noqa: S603, S607 - the user's git on PATH, no shell


def tag(root: Path) -> str:
    """Create the annotated tag for the current version on a clean HEAD. Never pushes."""
    problems = check(root)
    if problems:
        raise ReleaseError("not ready to tag:\n  " + "\n  ".join(problems))
    status = _git(root, "status", "--porcelain")
    if status.returncode:
        raise ReleaseError(f"git status failed: {status.stderr.strip()}")
    if status.stdout.strip():
        raise ReleaseError("the working tree has uncommitted changes; commit them before tagging")
    version = current_version(root)
    name = tag_for(version)
    if _git(root, "rev-parse", "-q", "--verify", f"refs/tags/{name}").returncode == 0:
        raise ReleaseError(f"tag {name} already exists; bump the version first")
    created = _git(root, "tag", "-a", name, "-m", f"{display_name(root)} {version}")
    if created.returncode:
        raise ReleaseError(f"git tag failed: {created.stderr.strip()}")
    return name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare a release: version, build, wheel check, tag.")
    parser.add_argument(
        "--root", type=Path, default=REPO_ROOT, help="repository to work on (default: this one)"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    check_parser = commands.add_parser("check", help="versions, changelog and (optionally) a tag agree")
    check_parser.add_argument("--tag", help="the tag being released, e.g. v0.1.0")
    bump_parser = commands.add_parser(
        "bump", help="write a new version into the package and the Node workspaces"
    )
    bump_parser.add_argument("part", help="major, minor, patch, or an explicit X.Y.Z")
    commands.add_parser("build", help="build wheel and sdist into dist/ and check the wheel")
    commands.add_parser("notes", help="print this version's CHANGELOG section")
    commands.add_parser("tag", help="create the local annotated tag v<version>")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        if args.command == "check":
            problems = check(root, args.tag)
            if problems:
                print("\n".join(problems), file=sys.stderr)
                return 1
            print(
                f"{display_name(root)} {current_version(root)}: version, changelog"
                + (f" and tag {args.tag}" if args.tag else "")
                + " agree"
            )
        elif args.command == "bump":
            new = bump(root, args.part)
            print(f"version is now {new}. Add a '## [{new}]' section to CHANGELOG.md, commit, then run tag.")
        elif args.command == "build":
            for path in build(root):
                print(path.relative_to(root))
            print("wheel contents checked")
        elif args.command == "notes":
            print(changelog_section(root, current_version(root)))
        elif args.command == "tag":
            name = tag(root)
            print(f"created tag {name}. Publish with: git push origin {name}")
    except ReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
