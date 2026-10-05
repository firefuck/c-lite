"""The rename script, run on a copy of this repository.

The README promises that the project can be renamed with one command. That holds only while
no file spells the name in a way the script cannot see, so the promise is checked by doing
it: copy the repository, rename it, look at what is left, and start the renamed program.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from clite import __version__
from clite.core.brand import APP_NAME, DISPLAY_NAME

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = Path("scripts") / "rename_project.py"

pytestmark = pytest.mark.skipif(not (REPO_ROOT / SCRIPT).is_file(), reason="not a source checkout")

# Names the project does not have now. After a real rename this file is rewritten along with
# everything else, so the second pair is there for a project that took the first.
NEW_NAME, NEW_DISPLAY = ("orbit", "Orbit") if APP_NAME != "orbit" else ("comet", "Comet")
THIRD_NAME, THIRD_DISPLAY = ("nimbus", "Nimbus") if APP_NAME != "nimbus" else ("comet", "Comet")

NOT_SOURCE = (".git", "node_modules", "dist", "build", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
              ".venv", "venv", "*.egg-info")


def _copy_repository(target: Path) -> Path:
    """What a commit of the working tree would contain, copied to ``target``. Outside a git
    checkout (a source archive), everything except caches and build output."""
    try:
        listed = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=REPO_ROOT,
                                capture_output=True, timeout=60)
        names = [name for name in listed.stdout.decode().split("\0") if name] if listed.returncode == 0 else []
    except (OSError, subprocess.TimeoutExpired):
        names = []
    if not names:
        shutil.copytree(REPO_ROOT, target, ignore=shutil.ignore_patterns(*NOT_SOURCE), symlinks=True)
        return target
    for name in names:
        source = REPO_ROOT / name
        if source.is_file() and not source.is_symlink():
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target / name)
    return target


def _rename(root: Path, name: str, display: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(root / SCRIPT), "--name", name, "--display", display, *extra],
                          capture_output=True, text=True, timeout=120)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _run_renamed(root: Path, name: str, home: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(root / "src"), *sys.path]), f"{name.upper()}_HOME": str(home),
           "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-m", name, *arguments], capture_output=True, text=True, timeout=120, env=env,
                          cwd=home)


def test_a_dry_run_reports_the_changes_and_makes_none(tmp_path):
    copy = _copy_repository(tmp_path / "copy")
    before = _snapshot(copy)
    result = _rename(copy, NEW_NAME, NEW_DISPLAY, "--dry-run")
    assert result.returncode == 0, result.stderr
    assert f"would move   src/{APP_NAME} -> {NEW_NAME}" in result.stdout
    assert "would edit   pyproject.toml" in result.stdout
    assert _snapshot(copy) == before


def test_renaming_leaves_no_trace_of_the_old_name_and_the_program_still_runs(tmp_path):
    copy = _copy_repository(tmp_path / "copy")
    result = _rename(copy, NEW_NAME, NEW_DISPLAY)
    assert result.returncode == 0, result.stderr
    assert not (copy / "src" / APP_NAME).exists()
    assert f'APP_NAME = "{NEW_NAME}"' in (copy / "src" / NEW_NAME / "core" / "brand.py").read_text()

    # The address of the repository is not the project's name: a `git clone` line keeps it.
    old_name = re.compile("|".join(re.escape(name) for name in {APP_NAME, DISPLAY_NAME}), re.IGNORECASE)
    left = []
    for path in sorted(copy.rglob("*")):
        if old_name.search(path.name):
            left.append(f"{path.relative_to(copy)} (file name)")
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        left += [f"{path.relative_to(copy)}:{number}: {line.strip()}" for number, line in enumerate(lines, 1)
                 if old_name.search(line) and "git clone " not in line]
    assert left == [], "these spell the old name in a way scripts/rename_project.py does not rewrite"

    home = tmp_path / "home"
    home.mkdir()
    version = _run_renamed(copy, NEW_NAME, home, "--version")
    assert version.returncode == 0, version.stderr
    assert version.stdout.strip() == f"{NEW_DISPLAY} {__version__}"
    turn = _run_renamed(copy, NEW_NAME, home, "chat", "-q", "still here", "--provider", "mock")
    assert turn.returncode == 0, turn.stderr
    assert turn.stdout.strip() == "You said: still here"
    assert (home / "state.db").is_file()  # the renamed home variable was honoured


def test_a_renamed_project_can_be_renamed_again(tmp_path):
    """The script reads the current name from the repository, not from its own source."""
    copy = _copy_repository(tmp_path / "copy")
    assert _rename(copy, NEW_NAME, NEW_DISPLAY).returncode == 0
    again = _rename(copy, THIRD_NAME, THIRD_DISPLAY)
    assert again.returncode == 0, again.stderr
    assert f"{NEW_NAME!r} ({NEW_DISPLAY!r}) -> {THIRD_NAME!r} ({THIRD_DISPLAY!r})" in again.stdout
    home = tmp_path / "home"
    home.mkdir()
    version = _run_renamed(copy, THIRD_NAME, home, "--version")
    assert version.returncode == 0, version.stderr
    assert version.stdout.strip() == f"{THIRD_DISPLAY} {__version__}"


def test_a_name_that_could_not_be_told_apart_is_refused(tmp_path):
    copy = _copy_repository(tmp_path / "copy")
    before = _snapshot(copy)
    for name, display in ((APP_NAME, "Same"), (f"{APP_NAME}two", "Two"), ("Bad-Name", "Bad")):
        result = _rename(copy, name, display)
        assert result.returncode == 2, (name, result.stdout)
    assert _snapshot(copy) == before
