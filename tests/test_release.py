"""The release script: one version, the tag that names it, and a wheel that carries the package.

A release is only consistent when ``__version__``, the version the build metadata reads,
``clite --version``, the changelog and the tag all say the same thing. These tests check that
on this repository, and check the script's refusals on small throwaway repositories.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path
from typing import Any

import pytest

from clite import __version__
from clite.core.brand import APP_NAME, DISPLAY_NAME

REPO_ROOT = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(
    not (REPO_ROOT / "scripts" / "release.py").is_file(), reason="not a source checkout"
)

sys.path.insert(0, str(REPO_ROOT / "scripts"))
try:
    import release
finally:
    sys.path.pop(0)


def _mini_repository(root: Path, version: str = "1.2.3") -> Path:
    """The files the release script reads, from this repository, with another version.

    It has no Node workspaces; ``_with_node_workspaces`` adds two."""
    package = root / "src" / APP_NAME
    (package / "core").mkdir(parents=True)
    shutil.copy2(REPO_ROOT / "src" / APP_NAME / "core" / "brand.py", package / "core" / "brand.py")
    (package / "__init__.py").write_text(f'"""Docstring."""\n\n__version__ = "{version}"\n', encoding="utf-8")
    shutil.copy2(REPO_ROOT / "pyproject.toml", root / "pyproject.toml")
    (root / "CHANGELOG.md").write_text(
        f"# Changes\n\n## [{version}] - 2026-01-01\n\n- Something.\n\n## [0.0.1]\n\n- Old.\n",
        encoding="utf-8",
    )
    return root


def _with_node_workspaces(root: Path, version: str) -> Path:
    workspaces = ["apps/app", "packages/lib"]
    (root / "package.json").write_text(json.dumps({"name": "w", "workspaces": workspaces}, indent=2) + "\n")
    lock: dict[str, Any] = {"name": "w", "lockfileVersion": 3, "packages": {"": {"workspaces": workspaces}}}
    for name in workspaces:
        (root / name).mkdir(parents=True)
        manifest = {"name": f"@w/{name.rsplit('/', 1)[1]}", "version": version, "private": True}
        (root / name / "package.json").write_text(json.dumps(manifest, indent=2) + "\n")
        lock["packages"][name] = {"name": manifest["name"], "version": version}
        lock["packages"][f"node_modules/{manifest['name']}"] = {"resolved": name, "link": True}
    (root / "package-lock.json").write_text(json.dumps(lock, indent=2) + "\n")
    return root


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=60, env=env)


def test_every_node_workspace_carries_the_package_version():
    """The desktop installer is named after its package.json; the others ship inside the wheel.
    `scripts/release.py bump` writes the version into all of them."""
    workspaces = json.loads((REPO_ROOT / "package.json").read_text(encoding="utf-8"))["workspaces"]
    versions = {
        name: json.loads((REPO_ROOT / name / "package.json").read_text(encoding="utf-8"))["version"]
        for name in workspaces
    }
    assert versions == dict.fromkeys(workspaces, __version__), (
        f"run `python scripts/release.py bump {__version__}` to set every workspace's version"
    )


def test_the_version_in_pyproject_the_cli_and_the_release_tag_are_the_same():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    # pyproject.toml takes the version from the package instead of spelling a second copy.
    assert project["tool"]["setuptools"]["dynamic"]["version"] == {"attr": f"{APP_NAME}.__version__"}
    assert release.current_version(REPO_ROOT) == __version__

    printed = subprocess.run(
        [sys.executable, "-m", APP_NAME, "--version"],
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")},
    )
    assert printed.returncode == 0, printed.stderr
    assert printed.stdout.strip() == f"{DISPLAY_NAME} {__version__}"

    tag = release.tag_for(__version__)
    assert tag == f"v{__version__}"
    assert release.check(REPO_ROOT, tag) == []


def test_the_distribution_is_published_as_c_lite_while_the_command_stays_clite():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] != APP_NAME  # the short name on PyPI belongs to another project
    assert project["scripts"][APP_NAME] == f"{APP_NAME}.cli.main:main"
    assert project["license"] == "MIT"


def test_the_project_links_point_at_the_repository_the_readme_clones():
    project = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    clone = re.search(r"git clone (https://github\.com/[\w.-]+/[\w.-]+)", readme)
    assert clone is not None
    urls = project["urls"]
    assert {"Homepage", "Documentation", "Issues", "Changelog"} <= set(urls)
    assert all(url.startswith(clone.group(1)) for name, url in urls.items() if name != "Documentation")


def test_a_tag_that_does_not_match_the_version_is_reported(tmp_path):
    root = _mini_repository(tmp_path)
    assert release.check(root, "v1.2.3") == []
    assert release.check(root, "v1.2.4") == ["tag v1.2.4 does not match version 1.2.3: expected v1.2.3"]


def test_a_second_spelled_out_version_or_a_missing_changelog_section_is_reported(tmp_path):
    root = _mini_repository(tmp_path)
    pyproject = root / "pyproject.toml"
    pyproject.write_text(
        pyproject.read_text(encoding="utf-8").replace('dynamic = ["version"]', 'version = "1.2.3"'),
        encoding="utf-8",
    )
    (root / "CHANGELOG.md").write_text("# Changes\n\n## [0.0.1]\n\n- Old.\n", encoding="utf-8")
    problems = "\n".join(release.check(root))
    assert "pyproject.toml spells the version" in problems
    assert "has no '## [1.2.3]' section" in problems


def test_bump_rewrites_the_one_version_and_nothing_else(tmp_path):
    root = _mini_repository(tmp_path)
    before = (root / "pyproject.toml").read_bytes()
    assert release.bump(root, "minor") == "1.3.0"
    assert release.current_version(root) == "1.3.0"
    assert release.bump(root, "patch") == "1.3.1"
    assert release.bump(root, "major") == "2.0.0"
    assert release.bump(root, "4.5.6") == "4.5.6"
    assert (root / "pyproject.toml").read_bytes() == before
    with pytest.raises(release.ReleaseError):
        release.bump(root, "sideways")


def test_bump_carries_the_version_into_every_node_workspace_and_the_lockfile(tmp_path):
    root = _with_node_workspaces(_mini_repository(tmp_path), "1.2.3")
    assert release.check(root) == []
    assert release.bump(root, "patch") == "1.2.4"
    for name in ("apps/app", "packages/lib"):
        assert json.loads((root / name / "package.json").read_text())["version"] == "1.2.4"
    lock = json.loads((root / "package-lock.json").read_text())
    assert [lock["packages"][name]["version"] for name in ("apps/app", "packages/lib")] == ["1.2.4", "1.2.4"]
    assert lock["packages"]["node_modules/@w/app"] == {"resolved": "apps/app", "link": True}
    changelog = root / "CHANGELOG.md"
    changelog.write_text(changelog.read_text().replace("# Changes\n", "# Changes\n\n## [1.2.4]\n\n- Fix.\n"))
    assert release.check(root) == []


def test_a_node_workspace_left_at_another_version_is_reported(tmp_path):
    root = _with_node_workspaces(_mini_repository(tmp_path), "1.2.3")
    manifest = root / "packages" / "lib" / "package.json"
    manifest.write_text(manifest.read_text().replace('"1.2.3"', '"1.0.0"'))
    assert release.check(root) == ["packages/lib/package.json has version '1.0.0', expected '1.2.3'"]


def test_the_release_notes_are_the_changelog_section_of_the_current_version(tmp_path):
    root = _mini_repository(tmp_path)
    assert release.changelog_section(root, "1.2.3") == "- Something."
    assert release.changelog_section(REPO_ROOT, __version__).strip()


def _wheel_from_package(root: Path, target: Path, *, leave_out: str | None = None) -> Path:
    """A wheel built by zipping the package directory, like a correct build would."""
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = release.current_version(root)
    dist_info = f"{project['name'].replace('-', '_')}-{version}.dist-info"
    wheel = target / f"{project['name'].replace('-', '_')}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name in sorted(release.expected_wheel_files(root)):
            if name != leave_out:
                archive.write(root / "src" / name, name)
        archive.writestr(
            f"{dist_info}/METADATA", f"Metadata-Version: 2.4\nName: {project['name']}\nVersion: {version}\n"
        )
        archive.writestr(
            f"{dist_info}/entry_points.txt", f"[console_scripts]\n{APP_NAME} = {APP_NAME}.cli.main:main\n"
        )
        archive.writestr(f"{dist_info}/licenses/LICENSE", "MIT")
    return wheel


def test_the_wheel_check_accepts_a_complete_wheel_and_names_what_is_missing(tmp_path):
    complete = _wheel_from_package(REPO_ROOT, tmp_path)
    assert release.inspect_wheel(complete, REPO_ROOT) == []

    skill = f"{APP_NAME}/bundled/skills/meta/skill-authoring/SKILL.md"
    assert skill in release.expected_wheel_files(REPO_ROOT)
    (tmp_path / "short").mkdir()
    short = _wheel_from_package(REPO_ROOT, tmp_path / "short", leave_out=skill)
    assert release.inspect_wheel(short, REPO_ROOT) == [f"missing from the wheel: {skill}"]


def test_area_instructions_for_contributors_are_not_expected_in_the_wheel():
    assert not any(name.endswith("/AGENTS.md") for name in release.expected_wheel_files(REPO_ROOT))


@pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
def test_tagging_needs_a_clean_tree_and_creates_the_tag_for_the_version(tmp_path):
    root = _mini_repository(tmp_path)
    assert _git(root, "init", "-q").returncode == 0
    # `release.tag` runs `git tag` with the ambient environment, so the throwaway repository
    # carries its own identity instead of relying on the machine's global config.
    assert _git(root, "config", "user.email", "t@example.invalid").returncode == 0
    assert _git(root, "config", "user.name", "t").returncode == 0
    assert _git(root, "add", "-A").returncode == 0
    assert _git(root, "commit", "-q", "-m", "init").returncode == 0

    (root / "stray.txt").write_text("not committed", encoding="utf-8")
    with pytest.raises(release.ReleaseError, match="uncommitted changes"):
        release.tag(root)
    (root / "stray.txt").unlink()

    assert release.tag(root) == "v1.2.3"
    assert _git(root, "tag", "--list").stdout.split() == ["v1.2.3"]
    with pytest.raises(release.ReleaseError, match="already exists"):
        release.tag(root)
