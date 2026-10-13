"""The pre-push hook: the checks a push must pass while CI cannot run.

Each test runs the real hook in a throwaway git repository whose ``scripts/run_tests.sh`` is a
stub, so what is checked here is the hook's own decisions, not the suite it starts.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / "scripts" / "hooks" / "pre-push"
ZERO = "0" * 40

pytestmark = pytest.mark.platforms("posix")


def _repository(tmp_path: Path, *, checks_pass: bool) -> Path:
    """A git repository holding the hook and a stub test runner that records each run."""
    repo = tmp_path / "repo"
    (repo / "scripts" / "hooks").mkdir(parents=True)
    shutil.copy2(HOOK, repo / "scripts" / "hooks" / "pre-push")
    runner = repo / "scripts" / "run_tests.sh"
    runner.write_text(f"#!/usr/bin/env bash\necho ran >> checks.log\nexit {0 if checks_pass else 1}\n")
    runner.chmod(runner.stat().st_mode | stat.S_IXUSR)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def _push(repo: Path, refs: str) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(
        [str(repo / "scripts" / "hooks" / "pre-push"), "origin", "https://example.invalid/repo.git"],
        input=refs,
        capture_output=True,
        text=True,
        cwd=repo,
        env=env,
        timeout=60,
    )


def test_the_hook_is_executable_so_git_runs_it():
    assert HOOK.stat().st_mode & stat.S_IXUSR


def test_a_push_with_commits_runs_the_checks_and_goes_through_when_they_pass(tmp_path):
    repo = _repository(tmp_path, checks_pass=True)
    result = _push(repo, f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}\n")
    assert result.returncode == 0, result.stderr
    assert (repo / "checks.log").read_text() == "ran\n"


def test_a_push_is_refused_when_the_checks_fail(tmp_path):
    repo = _repository(tmp_path, checks_pass=False)
    result = _push(repo, f"refs/heads/main {'a' * 40} refs/heads/main {ZERO}\n")
    assert result.returncode == 1
    assert "nothing was pushed" in result.stderr


def test_a_push_that_only_deletes_remote_refs_needs_no_checks(tmp_path):
    repo = _repository(tmp_path, checks_pass=False)
    result = _push(repo, f"(delete) {ZERO} refs/heads/old {'b' * 40}\n")
    assert result.returncode == 0, result.stderr
    assert not (repo / "checks.log").exists()
