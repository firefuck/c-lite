"""File tools: paging, safe writes, unambiguous patches, search."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from clite.core.env import load_env
from clite.tools.builtin.file_tools import patch_tool, read_file_tool, search_files_tool, write_file_tool
from clite.tools.context import ToolContext
from clite.tools.file_safety import read_denied_reason, write_denied_reason


@pytest.fixture
def ctx(tmp_path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return ToolContext(task_id="files", cwd=str(workspace))


def _ws(ctx) -> Path:
    return Path(ctx.cwd)


def test_read_returns_numbered_lines(ctx):
    (_ws(ctx) / "a.txt").write_text("one\ntwo\nthree\n")
    result = json.loads(read_file_tool({"path": "a.txt"}, ctx))
    assert result["content"] == "1|one\n2|two\n3|three"
    assert result["total_lines"] == 3 and "truncated" not in result


def test_read_pages_with_offset_and_limit(ctx):
    (_ws(ctx) / "long.txt").write_text("\n".join(f"line {n}" for n in range(1, 21)))
    first = json.loads(read_file_tool({"path": "long.txt", "limit": 5}, ctx))
    assert first["truncated"] is True and first["next_offset"] == 6
    second = json.loads(read_file_tool({"path": "long.txt", "offset": first["next_offset"], "limit": 5}, ctx))
    assert second["content"].splitlines()[0] == "6|line 6"


def test_read_respects_the_character_budget(ctx, clite_home):
    (clite_home / "config.yaml").write_text("file_read_max_chars: 60\n")
    (_ws(ctx) / "wide.txt").write_text("\n".join("x" * 20 for _ in range(10)))
    result = json.loads(read_file_tool({"path": "wide.txt"}, ctx))
    assert result["truncated"] is True and len(result["content"]) <= 80


def test_read_missing_file_suggests_neighbours(ctx):
    (_ws(ctx) / "config.yaml").write_text("a: 1\n")
    result = json.loads(read_file_tool({"path": "config.yml"}, ctx))
    assert "not found" in result["error"]
    assert result["suggestions"] == [str(_ws(ctx) / "config.yaml")]


def test_read_refuses_binary_and_directories(ctx):
    (_ws(ctx) / "blob.bin").write_bytes(b"\x00\x01\x02")
    assert "binary" in json.loads(read_file_tool({"path": "blob.bin"}, ctx))["error"]
    assert "directory" in json.loads(read_file_tool({"path": "."}, ctx))["error"]


def test_write_creates_parents_and_reports_creation(ctx):
    created = json.loads(write_file_tool({"path": "pkg/mod/a.py", "content": "x = 1\n"}, ctx))
    assert created["created"] is True
    assert (_ws(ctx) / "pkg/mod/a.py").read_text() == "x = 1\n"
    assert json.loads(write_file_tool({"path": "pkg/mod/a.py", "content": "x = 2\n"}, ctx))["created"] is False


def test_relative_paths_follow_the_terminal_cwd(ctx):
    from clite.tools.environments import get_environment

    (_ws(ctx) / "sub").mkdir()
    get_environment("files", cwd=ctx.cwd).cwd = str(_ws(ctx) / "sub")
    write_file_tool({"path": "here.txt", "content": "hi"}, ctx)
    assert (_ws(ctx) / "sub" / "here.txt").exists()


def test_agent_cannot_write_its_own_credentials_or_settings(ctx, clite_home):
    for name in (".env", "config.yaml"):
        result = json.loads(write_file_tool({"path": str(clite_home / name), "content": "x"}, ctx))
        assert "Refused" in result["error"]
        assert not (clite_home / name).exists()
    assert write_denied_reason(Path.home() / ".ssh" / "authorized_keys")
    assert write_denied_reason(clite_home / "skills" / "note" / "SKILL.md") is None


def test_every_profile_and_the_pairing_store_are_guarded_like_the_active_home(ctx, clite_home):
    """A profile is a home of its own, and gateway/pairing.json decides which chat users may
    talk to the agent: both are settings the agent must not edit."""
    other = clite_home / "profiles" / "work"
    other.mkdir(parents=True)
    (other / ".env").write_text("WORK_API_KEY=sk-work-very-secret-value-123456\n")
    assert "Refused" in json.loads(read_file_tool({"path": str(other / ".env")}, ctx))["error"]
    for target in (other / ".env", other / "config.yaml", clite_home / "profiles" / "not-made-yet" / "config.yaml",
                   clite_home / "gateway" / "pairing.json", other / "gateway" / "pairing.json", clite_home / "CONFIG.YAML"):
        result = json.loads(write_file_tool({"path": str(target), "content": "x"}, ctx))
        assert "Refused" in result["error"], target
    assert (other / ".env").read_text().startswith("WORK_API_KEY=")
    assert write_denied_reason(clite_home / "gateway" / "sessions.json") is None
    assert read_denied_reason(other / "config.yaml") is None  # policy, not credentials: readable


def test_credential_files_cannot_be_read(ctx, clite_home):
    (clite_home / ".env").write_text("OPENROUTER_API_KEY=sk-or-very-secret-value-123456\n")
    result = json.loads(read_file_tool({"path": str(clite_home / ".env")}, ctx))
    assert "Refused" in result["error"] and "very-secret" not in json.dumps(result)

    ssh = Path.home() / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text("-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----\n")
    assert "Refused" in json.loads(read_file_tool({"path": str(ssh / "id_ed25519")}, ctx))["error"]
    # A content search across the home directory does not return them either.
    found = json.loads(search_files_tool({"pattern": "PRIVATE KEY|very-secret", "path": str(Path.home())}, ctx))
    assert found["count"] == 0

    # Settings hold no secrets (they name them), so they stay readable.
    assert read_denied_reason(clite_home / "config.yaml") is None


def test_credentials_are_redacted_from_what_the_model_reads(ctx, clite_home):
    """Whatever a file tool returns is sent to the model provider and stored in the session."""
    (clite_home / ".env").write_text("DEPLOY_TOKEN=correct-horse-battery-staple\n")
    load_env()
    target = _ws(ctx) / "deploy.sh"
    target.write_text("export DEPLOY=correct-horse-battery-staple\nexport OPENAI=sk-abcdefghijklmnopqrstuvwxyz123456\necho done\n")

    read = json.loads(read_file_tool({"path": "deploy.sh"}, ctx))
    assert "correct-horse" not in read["content"] and "sk-abcdef" not in read["content"]
    assert read["content"].count("[REDACTED]") == 2 and "3|echo done" in read["content"]
    assert "[REDACTED]" in read["note"]

    found = json.loads(search_files_tool({"pattern": "export"}, ctx))
    assert found["count"] == 2 and "correct-horse" not in json.dumps(found) and "sk-abcdef" not in json.dumps(found)

    patched = json.loads(patch_tool({"path": "deploy.sh", "old_string": "echo done", "new_string": "echo finished"}, ctx))
    assert "+echo finished" in patched["diff"] and "sk-abcdef" not in patched["diff"]
    assert "sk-abcdefghijklmnopqrstuvwxyz123456" in target.read_text()  # the file itself is untouched

    assert "note" not in json.loads(read_file_tool({"path": "deploy.sh", "offset": 3}, ctx))


@pytest.mark.platforms("posix")
def test_a_pipe_or_device_is_refused_instead_of_blocking(ctx):
    pipe = _ws(ctx) / "queue"
    os.mkfifo(pipe)
    assert "not a regular file" in json.loads(read_file_tool({"path": "queue"}, ctx))["error"]
    assert "not a regular file" in json.loads(read_file_tool({"path": "/dev/zero"}, ctx))["error"]


def test_patch_replaces_a_unique_match_and_returns_a_diff(ctx):
    target = _ws(ctx) / "app.py"
    target.write_text("def a():\n    return 1\n\ndef b():\n    return 2\n")
    result = json.loads(patch_tool({"path": "app.py", "old_string": "return 1", "new_string": "return 10"}, ctx))
    assert result["replacements"] == 1
    assert "-    return 1" in result["diff"] and "+    return 10" in result["diff"]
    assert "return 10" in target.read_text()


def test_patch_refuses_an_ambiguous_match(ctx):
    target = _ws(ctx) / "app.py"
    target.write_text("x = 1\nx = 1\n")
    result = json.loads(patch_tool({"path": "app.py", "old_string": "x = 1", "new_string": "x = 2"}, ctx))
    assert result["matches"] == 2
    assert target.read_text() == "x = 1\nx = 1\n"
    patch_tool({"path": "app.py", "old_string": "x = 1", "new_string": "x = 2", "replace_all": True}, ctx)
    assert target.read_text() == "x = 2\nx = 2\n"


def test_patch_tolerates_wrong_indentation_when_the_match_is_unique(ctx):
    target = _ws(ctx) / "app.py"
    target.write_text("class A:\n    def run(self):\n        return 1\n")
    result = json.loads(
        patch_tool({"path": "app.py", "old_string": "def run(self):\n    return 1", "new_string": "    def run(self):\n        return 2"}, ctx)
    )
    assert result["replacements"] == 1
    assert target.read_text() == "class A:\n    def run(self):\n        return 2\n"


def test_patch_reports_a_missing_match_without_touching_the_file(ctx):
    target = _ws(ctx) / "app.py"
    target.write_text("a = 1\n")
    assert "not found" in json.loads(patch_tool({"path": "app.py", "old_string": "b = 2", "new_string": "c"}, ctx))["error"]
    assert target.read_text() == "a = 1\n"


def test_search_content_reports_path_line_and_text(ctx):
    (_ws(ctx) / "src").mkdir()
    (_ws(ctx) / "src" / "a.py").write_text("import os\n\ndef handler():\n    pass\n")
    (_ws(ctx) / "src" / "b.md").write_text("the handler is documented here\n")
    result = json.loads(search_files_tool({"pattern": r"def \w+\("}, ctx))
    assert result["matches"] == ["src/a.py:3: def handler():"]
    assert json.loads(search_files_tool({"pattern": "handler", "file_glob": "*.md"}, ctx))["count"] == 1
    assert json.loads(search_files_tool({"pattern": "HANDLER", "ignore_case": True}, ctx))["count"] == 2


def test_search_skips_dependency_and_vcs_directories(ctx):
    for directory in ("node_modules/pkg", ".git", "src"):
        (_ws(ctx) / directory).mkdir(parents=True)
        (_ws(ctx) / directory / "f.js").write_text("needle\n")
    result = json.loads(search_files_tool({"pattern": "needle"}, ctx))
    assert result["matches"] == ["src/f.js:1: needle"]


def test_search_files_by_glob_and_limit(ctx):
    for name in ("a.py", "b.py", "c.txt"):
        (_ws(ctx) / name).write_text("")
    assert json.loads(search_files_tool({"pattern": "*.py", "target": "files"}, ctx))["files"] == ["a.py", "b.py"]
    limited = json.loads(search_files_tool({"pattern": "*", "target": "files", "limit": 1}, ctx))
    assert limited["count"] == 1 and limited["truncated"] is True


def test_search_rejects_a_bad_regex(ctx):
    assert "invalid regular expression" in json.loads(search_files_tool({"pattern": "("}, ctx))["error"]
