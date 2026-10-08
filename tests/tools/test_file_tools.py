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
from clite.tools.patching import find_tolerant_match


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
    assert (
        json.loads(write_file_tool({"path": "pkg/mod/a.py", "content": "x = 2\n"}, ctx))["created"] is False
    )


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
    for target in (
        other / ".env",
        other / "config.yaml",
        clite_home / "profiles" / "not-made-yet" / "config.yaml",
        clite_home / "gateway" / "pairing.json",
        other / "gateway" / "pairing.json",
        clite_home / "CONFIG.YAML",
    ):
        result = json.loads(write_file_tool({"path": str(target), "content": "x"}, ctx))
        assert "Refused" in result["error"], target
    assert (other / ".env").read_text().startswith("WORK_API_KEY=")
    assert write_denied_reason(clite_home / "gateway" / "sessions.json") is None
    assert read_denied_reason(other / "config.yaml") is None  # policy, not credentials: readable


def test_profiles_under_an_overridden_home_are_guarded(tmp_path):
    from clite.core.constants import home_scope

    with home_scope(tmp_path / "custom-home"):
        assert read_denied_reason(tmp_path / "custom-home" / "profiles" / "work" / ".env")
        assert write_denied_reason(tmp_path / "custom-home" / "profiles" / "work" / "config.yaml")


def test_credential_files_cannot_be_read(ctx, clite_home):
    (clite_home / ".env").write_text("OPENROUTER_API_KEY=sk-or-very-secret-value-123456\n")
    result = json.loads(read_file_tool({"path": str(clite_home / ".env")}, ctx))
    assert "Refused" in result["error"] and "very-secret" not in json.dumps(result)

    ssh = Path.home() / ".ssh"
    ssh.mkdir()
    (ssh / "id_ed25519").write_text(
        "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----\n"
    )
    assert "Refused" in json.loads(read_file_tool({"path": str(ssh / "id_ed25519")}, ctx))["error"]
    # A content search across the home directory does not return them either.
    found = json.loads(
        search_files_tool({"pattern": "PRIVATE KEY|very-secret", "path": str(Path.home())}, ctx)
    )
    assert found["count"] == 0

    # Settings hold no secrets (they name them), so they stay readable.
    assert read_denied_reason(clite_home / "config.yaml") is None


def test_credentials_are_redacted_from_what_the_model_reads(ctx, clite_home):
    """Whatever a file tool returns is sent to the model provider and stored in the session."""
    (clite_home / ".env").write_text("DEPLOY_TOKEN=correct-horse-battery-staple\n")
    load_env()
    target = _ws(ctx) / "deploy.sh"
    target.write_text(
        "export DEPLOY=correct-horse-battery-staple\nexport OPENAI=sk-abcdefghijklmnopqrstuvwxyz123456\necho done\n"
    )

    read = json.loads(read_file_tool({"path": "deploy.sh"}, ctx))
    assert "correct-horse" not in read["content"] and "sk-abcdef" not in read["content"]
    assert read["content"].count("[REDACTED]") == 2 and "3|echo done" in read["content"]
    assert "[REDACTED]" in read["note"]

    found = json.loads(search_files_tool({"pattern": "export"}, ctx))
    assert (
        found["count"] == 2
        and "correct-horse" not in json.dumps(found)
        and "sk-abcdef" not in json.dumps(found)
    )

    patched = json.loads(
        patch_tool({"path": "deploy.sh", "old_string": "echo done", "new_string": "echo finished"}, ctx)
    )
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
    result = json.loads(
        patch_tool({"path": "app.py", "old_string": "return 1", "new_string": "return 10"}, ctx)
    )
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
        patch_tool(
            {
                "path": "app.py",
                "old_string": "def run(self):\n    return 1",
                "new_string": "    def run(self):\n        return 2",
            },
            ctx,
        )
    )
    assert result["replacements"] == 1
    assert target.read_text() == "class A:\n    def run(self):\n        return 2\n"


def test_patch_reports_a_missing_match_without_touching_the_file(ctx):
    target = _ws(ctx) / "app.py"
    target.write_text("a = 1\n")
    assert (
        "not found"
        in json.loads(patch_tool({"path": "app.py", "old_string": "b = 2", "new_string": "c"}, ctx))["error"]
    )
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
    assert json.loads(search_files_tool({"pattern": "*.py", "target": "files"}, ctx))["files"] == [
        "a.py",
        "b.py",
    ]
    limited = json.loads(search_files_tool({"pattern": "*", "target": "files", "limit": 1}, ctx))
    assert limited["count"] == 1 and limited["truncated"] is True


def test_search_rejects_a_bad_regex(ctx):
    assert "invalid regular expression" in json.loads(search_files_tool({"pattern": "("}, ctx))["error"]


# ── tolerance chain: one unique-match and one ambiguous-rejected test per rung ──────────


def test_exact_match_reports_the_exact_level(ctx):
    """Level 0: a verbatim match is reported as 'exact', not via the fuzzy chain."""
    target = _ws(ctx) / "app.py"
    target.write_text("def a():\n    return 1\n")
    result = json.loads(
        patch_tool({"path": "app.py", "old_string": "return 1", "new_string": "return 10"}, ctx)
    )
    assert result["replacements"] == 1
    assert result["match_level"] == "exact"
    assert "return 10" in target.read_text()


def test_trailing_whitespace_match_is_unique_and_reports_the_level(ctx):
    """Level 1: trailing whitespace on old_string still matches when the result is unique."""
    target = _ws(ctx) / "app.py"
    target.write_text("def a():\n    return 1\n")
    # old_string has trailing spaces after 'return 1' that the file does not.
    result = json.loads(
        patch_tool({"path": "app.py", "old_string": "return 1   ", "new_string": "return 10"}, ctx)
    )
    assert result["replacements"] == 1
    assert result["match_level"] == "trailing_ws"
    assert "return 10" in target.read_text()


def test_trailing_whitespace_match_is_rejected_when_ambiguous(ctx):
    """Two lines differing only in trailing whitespace must not be silently patched."""
    target = _ws(ctx) / "app.py"
    target.write_text("x = 1\nx = 1\n")
    result = json.loads(patch_tool({"path": "app.py", "old_string": "x = 1   ", "new_string": "x = 2"}, ctx))
    assert "error" in result
    assert result.get("matches") == 2
    assert target.read_text() == "x = 1\nx = 1\n"


def test_indentation_match_is_unique_and_reports_the_level(ctx):
    """Level 2: wrong indentation on old_string still matches when unique (the pre-existing
    behaviour, now reported as 'indent')."""
    target = _ws(ctx) / "app.py"
    target.write_text("class A:\n    def run(self):\n        return 1\n")
    result = json.loads(
        patch_tool(
            {
                "path": "app.py",
                "old_string": "def run(self):\n    return 1",
                "new_string": "    def run(self):\n        return 2",
            },
            ctx,
        )
    )
    assert result["replacements"] == 1
    assert result["match_level"] == "indent"
    assert target.read_text() == "class A:\n    def run(self):\n        return 2\n"


def test_indentation_match_is_rejected_when_ambiguous(ctx):
    """Two blocks with the same stripped text must not be patched by the indent rung."""
    target = _ws(ctx) / "app.py"
    target.write_text(
        "class A:\n    def run(self):\n        return 1\n\nclass B:\n    def run(self):\n        return 1\n"
    )
    # old_string without leading indentation; both blocks strip to the same text.
    result = json.loads(
        patch_tool(
            {
                "path": "app.py",
                "old_string": "def run(self):\n        return 1",
                "new_string": "def run(self):\n        return 9",
            },
            ctx,
        )
    )
    assert "error" in result
    assert result.get("matches") == 2
    assert "return 1" in target.read_text()


def test_smart_quote_match_is_unique_and_reports_the_level(ctx):
    """Level 3: typographic quotes in old_string match ASCII quotes in the file."""
    target = _ws(ctx) / "note.md"
    target.write_text('The quick "brown" fox\n')
    # old_string uses smart quotes \u201c \u201d
    result = json.loads(
        patch_tool(
            {"path": "note.md", "old_string": "\u201cbrown\u201d fox", "new_string": "\u201cred\u201d fox"},
            ctx,
        )
    )
    assert result["replacements"] == 1
    assert result["match_level"] == "smart_quotes"
    assert "red" in target.read_text()


def test_smart_quote_match_is_rejected_when_ambiguous(ctx):
    """Two occurrences of the same smart-quote-normalised text must not be patched."""
    target = _ws(ctx) / "note.md"
    target.write_text('say "hi"\nsay "hi"\n')
    result = json.loads(
        patch_tool({"path": "note.md", "old_string": "\u201chi\u201d", "new_string": "\u201cbye\u201d"}, ctx)
    )
    assert "error" in result
    assert result.get("matches") == 2
    assert target.read_text() == 'say "hi"\nsay "hi"\n'


def test_blank_line_match_is_unique_and_reports_the_level(ctx):
    """Level 4: a missing blank line in old_string still matches when unique."""
    target = _ws(ctx) / "app.py"
    target.write_text("import os\n\n\ndef main():\n    pass\n")
    # old_string collapses the double blank line into one.
    result = json.loads(
        patch_tool(
            {
                "path": "app.py",
                "old_string": "import os\n\ndef main():",
                "new_string": "import sys\n\ndef main():",
            },
            ctx,
        )
    )
    assert result["replacements"] == 1
    assert result["match_level"] == "blank_lines"
    assert "import sys" in target.read_text()


def test_blank_line_match_is_rejected_when_ambiguous(ctx):
    """Two blocks whose only difference is blank-line count must not be patched."""
    target = _ws(ctx) / "app.py"
    # Each block has a double blank line between its two lines.
    target.write_text("x = 1\n\n\ny = 2\nx = 1\n\n\ny = 2\n")
    # old_string collapses the double blank to a single blank; both blocks match.
    result = json.loads(
        patch_tool({"path": "app.py", "old_string": "x = 1\n\ny = 2", "new_string": "x = 1\n\ny = 3"}, ctx)
    )
    assert "error" in result
    assert result.get("matches") == 2
    assert "y = 3" not in target.read_text()


def test_tolerance_chain_reports_matches_count_when_nothing_matches(ctx):
    """When every rung sees zero candidates, the error says 'not found' and matches is 0."""
    target = _ws(ctx) / "app.py"
    target.write_text("a = 1\n")
    result = json.loads(patch_tool({"path": "app.py", "old_string": "b = 2", "new_string": "c"}, ctx))
    assert "not found" in result["error"]
    assert result.get("matches") == 0
    assert target.read_text() == "a = 1\n"


# ── multi-file V4A patch mode ──────────────────────────────────────────────────────────


def _v4a(*lines: str) -> str:
    return "\n".join(lines)


def test_multi_file_patch_updates_two_files_atomically(ctx):
    a = _ws(ctx) / "a.py"
    a.write_text("x = 1\n")
    b = _ws(ctx) / "b.py"
    b.write_text("y = 2\n")
    patch = _v4a(
        "*** Update File: a.py",
        "-x = 1",
        "+x = 10",
        "*** Update File: b.py",
        "-y = 2",
        "+y = 20",
    )
    result = json.loads(
        patch_tool({"path": ".", "old_string": "", "new_string": "", "mode": "patch", "patch": patch}, ctx)
    )
    assert result["count"] == 2
    assert a.read_text() == "x = 10\n"
    assert b.read_text() == "y = 20\n"
    assert any("+x = 10" in f["diff"] for f in result["files"])
    assert any("+y = 20" in f["diff"] for f in result["files"])


def test_multi_file_patch_rolls_back_when_the_third_file_fails(ctx):
    """A failure on the third file must restore the first and second to their original state."""
    a = _ws(ctx) / "a.py"
    a.write_text("x = 1\n")
    b = _ws(ctx) / "b.py"
    b.write_text("y = 2\n")
    c = _ws(ctx) / "c.py"
    c.write_text("z = 3\n")
    original_a, original_b, original_c = a.read_text(), b.read_text(), c.read_text()
    patch = _v4a(
        "*** Update File: a.py",
        "-x = 1",
        "+x = 10",
        "*** Update File: b.py",
        "-y = 2",
        "+y = 20",
        "*** Update File: c.py",
        "-not_in_file",
        "+z = 30",
    )
    result = json.loads(
        patch_tool({"path": ".", "old_string": "", "new_string": "", "mode": "patch", "patch": patch}, ctx)
    )
    assert "error" in result
    assert result.get("rolled_back") is True
    # First and second files are unchanged; the third was never written.
    assert a.read_text() == original_a
    assert b.read_text() == original_b
    assert c.read_text() == original_c


def test_multi_file_patch_adds_and_deletes_files(ctx):
    target = _ws(ctx) / "old.py"
    target.write_text("gone = True\n")
    patch = _v4a(
        "*** Add File: new.py",
        "+created = True",
        "*** Delete File: old.py",
        "-gone = True",
    )
    result = json.loads(
        patch_tool({"path": ".", "old_string": "", "new_string": "", "mode": "patch", "patch": patch}, ctx)
    )
    assert result["count"] == 2
    new_file = _ws(ctx) / "new.py"
    assert new_file.read_text() == "created = True\n"
    assert not target.exists()
    added = next(f for f in result["files"] if f["path"].endswith("new.py"))
    assert added["created"] is True


def test_multi_file_patch_refuses_env_and_rolls_back_untouched(ctx, clite_home):
    """A patch that names the agent's own .env is refused entirely; files already written are rolled back."""
    a = _ws(ctx) / "a.py"
    a.write_text("x = 1\n")
    original_a = a.read_text()
    env_path = clite_home / ".env"
    env_path.write_text("KEY=value\n")
    patch = _v4a(
        "*** Update File: a.py",
        "-x = 1",
        "+x = 10",
        f"*** Update File: {env_path}",
        "-KEY=value",
        "+KEY=hacked",
    )
    result = json.loads(
        patch_tool({"path": ".", "old_string": "", "new_string": "", "mode": "patch", "patch": patch}, ctx)
    )
    assert "error" in result
    assert result.get("denied_path") == str(env_path)
    # The .env was never modified, and the first file was rolled back.
    assert env_path.read_text() == "KEY=value\n"
    assert a.read_text() == original_a


def test_multi_file_patch_requires_patch_argument(ctx):
    result = json.loads(patch_tool({"path": ".", "old_string": "", "new_string": "", "mode": "patch"}, ctx))
    assert "error" in result
    assert "patch" in result["error"]


def test_multi_file_patch_rejects_a_bad_format(ctx):
    result = json.loads(
        patch_tool(
            {"path": ".", "old_string": "", "new_string": "", "mode": "patch", "patch": "not v4a"}, ctx
        )
    )
    assert "error" in result
    assert "no file headers" in result["error"]


def test_multi_file_patch_diff_is_redacted(ctx, clite_home):
    """The diff returned by multi-file patch mode is redacted, like single-file patch."""
    (clite_home / ".env").write_text("DEPLOY_TOKEN=correct-horse-battery-staple\n")
    load_env()
    target = _ws(ctx) / "deploy.sh"
    target.write_text("export DEPLOY=correct-horse-battery-staple\necho done\n")
    patch = _v4a(
        "*** Update File: deploy.sh",
        "-echo done",
        "+echo finished",
    )
    result = json.loads(
        patch_tool({"path": ".", "old_string": "", "new_string": "", "mode": "patch", "patch": patch}, ctx)
    )
    assert result["count"] == 1
    diff = result["files"][0]["diff"]
    assert "+echo finished" in diff
    assert "correct-horse" not in diff


# ── tolerance chain, unit-level ─────────────────────────────────────────────────────────


def test_find_tolerant_match_returns_exact_for_a_verbatim_hit():
    match = find_tolerant_match("hello world\n", "hello world")
    assert match.found and match.level == "exact"


def test_find_tolerant_match_returns_none_for_zero_candidates():
    match = find_tolerant_match("a = 1\n", "b = 2")
    assert not match.found and match.matches == 0
