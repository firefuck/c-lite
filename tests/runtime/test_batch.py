"""The batch runner and the trajectory export (F6-T8).

The batch tests run the command for real, against the offline ``mock`` provider: three prompts
in, three records out, one of which is allowed to fail. The trajectory tests check what leaves
the machine — the steps, and what must not be in them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clite.cli.main import main
from clite.core.config import load_config
from clite.core.env import secret_scope
from clite.runtime.batch import RESULTS_FILENAME, BatchError, read_results, read_rows
from clite.runtime.factory import default_toolsets
from clite.runtime.trajectory import FORMAT, build_trajectory
from clite.state import get_session_db

MOCK = "model:\n  provider: mock\n  default: mock-1\n"
SECRET = "sk-batch-secret-value-1234567890"


@pytest.fixture
def cli(clite_home, capsys):
    (clite_home / "config.yaml").write_text(MOCK)

    def run(*argv, expect=0):
        code = main([str(arg) for arg in argv])
        captured = capsys.readouterr()
        assert code == expect, f"exit {code}\nstdout: {captured.out}\nstderr: {captured.err}"
        return captured.out

    return run


def write_lines(path: Path, *entries: dict[str, object]) -> Path:
    path.write_text("".join(json.dumps(entry) + "\n" for entry in entries), encoding="utf-8")
    return path


def three_prompts(tmp_path: Path) -> Path:
    return write_lines(
        tmp_path / "prompts.jsonl",
        {"id": "p1", "prompt": "question one"},
        {"id": "p2", "prompt": "question two"},
        {"id": "p3", "prompt": "question three"},
    )


# ── the batch runner ─────────────────────────────────────────────────────────────────────


def test_three_prompts_with_two_workers_write_three_results(cli, tmp_path):
    source = three_prompts(tmp_path)
    out_dir = tmp_path / "out"
    output = cli("batch", "run", str(source), "--workers", "2", "--out", str(out_dir))
    records = read_results(out_dir)
    assert {record["id"] for record in records} == {"p1", "p2", "p3"}
    assert all(record["status"] == "completed" for record in records)
    assert all(record["usage"]["output_tokens"] > 0 for record in records)
    assert all(record["duration_seconds"] >= 0 for record in records)
    assert "3 completed, 0 failed" in output
    assert (out_dir / RESULTS_FILENAME).exists()
    # Each prompt ran in a session of its own, on the batch platform.
    assert len({record["session_id"] for record in records}) == 3
    assert {row["source"] for row in get_session_db().list_sessions(limit=10)} == {"batch"}
    # The offline provider echoes the prompt, so the answer proves which line ran where.
    answers = {record["id"]: record["final_response"] for record in records}
    assert answers["p2"] == "You said: question two"


def test_the_batch_platform_gets_the_headless_toolset():
    assert default_toolsets("batch", load_config()) == ["clite-cron"]


def test_running_again_skips_the_rows_already_done(cli, tmp_path):
    source = three_prompts(tmp_path)
    out_dir = tmp_path / "out"
    cli("batch", "run", str(source), "--workers", "2", "--out", str(out_dir))
    first = (out_dir / RESULTS_FILENAME).read_text(encoding="utf-8")
    output = cli("batch", "run", str(source), "--workers", "2", "--out", str(out_dir))
    assert "0 completed, 0 failed, 3 already done" in output
    assert (out_dir / RESULTS_FILENAME).read_text(encoding="utf-8") == first
    assert len(get_session_db().list_sessions(limit=10)) == 3  # nothing ran a second time


def test_a_failing_prompt_does_not_stop_the_batch(cli, tmp_path):
    source = write_lines(
        tmp_path / "prompts.jsonl",
        {"id": "fine", "prompt": "all good"},
        {"id": "broken", "prompt": "!error 400"},
        {"id": "later", "prompt": "still runs"},
    )
    out_dir = tmp_path / "out"
    cli("batch", "run", str(source), "--workers", "2", "--out", str(out_dir), expect=1)
    records = {record["id"]: record for record in read_results(out_dir)}
    assert records["fine"]["status"] == "completed"
    assert records["later"]["status"] == "completed"
    assert records["broken"]["status"] == "failed"
    assert "400" in records["broken"]["error"]


def test_a_failed_row_is_tried_again_next_time(cli, tmp_path):
    source = write_lines(
        tmp_path / "prompts.jsonl",
        {"id": "fine", "prompt": "all good"},
        {"id": "broken", "prompt": "!error 400"},
    )
    out_dir = tmp_path / "out"
    cli("batch", "run", str(source), "--out", str(out_dir), expect=1)
    # The prompt is what was wrong, so the user fixes it and runs the same file again.
    fixed = write_lines(
        source,
        {"id": "fine", "prompt": "all good"},
        {"id": "broken", "prompt": "fixed now"},
    )
    output = cli("batch", "run", str(fixed), "--out", str(out_dir))
    assert "1 completed, 0 failed, 1 already done" in output
    records = {record["id"]: record for record in read_results(out_dir)}
    assert records["broken"]["status"] == "completed"
    assert records["broken"]["final_response"] == "You said: fixed now"


def test_a_bad_batch_file_is_refused_with_its_line(tmp_path):
    cases = [
        ("not JSON at all", "not json\n"),
        ("a list, not an object", "[]\n"),
        ("no prompt", '{"id": "a"}\n'),
        ("an empty prompt", '{"prompt": "   "}\n'),
        ("an unknown key", '{"prompt": "hi", "extra": 1}\n'),
        ("a repeated id", '{"id": "a", "prompt": "hi"}\n{"id": "a", "prompt": "ho"}\n'),
        ("toolsets that are not a list", '{"prompt": "hi", "toolsets": "file"}\n'),
        ("no prompts", "\n\n"),
    ]
    path = tmp_path / "bad.jsonl"
    for description, text in cases:
        path.write_text(text, encoding="utf-8")
        with pytest.raises(BatchError) as caught:
            read_rows(path)
        assert "bad.jsonl" in str(caught.value), description


def test_a_missing_batch_file_is_reported(tmp_path):
    with pytest.raises(BatchError):
        read_rows(tmp_path / "nope.jsonl")


def test_the_result_file_never_holds_a_known_credential(cli, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", SECRET)
    source = write_lines(tmp_path / "prompts.jsonl", {"id": "leaky", "prompt": f"my key is {SECRET}"})
    out_dir = tmp_path / "out"
    cli("batch", "run", str(source), "--out", str(out_dir))
    written = (out_dir / RESULTS_FILENAME).read_text(encoding="utf-8")
    assert SECRET not in written
    assert "[REDACTED]" in written


def test_a_written_results_file_survives_a_half_line(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / RESULTS_FILENAME).write_text(
        '{"id": "done", "status": "completed"}\n{"id": "cut off, no new',
        encoding="utf-8",
    )
    results = read_results(out_dir)
    assert [record["id"] for record in results] == ["done"]


# ── the trajectory export ────────────────────────────────────────────────────────────────


def test_the_trajectory_export_is_the_conversation_with_its_tool_calls(cli, tmp_path):
    (tmp_path / "data.txt").write_text("forty-two\n", encoding="utf-8")
    cli("-q", '!read_file {"path": "data.txt"}')
    session_id = get_session_db().list_sessions()[0]["id"]
    target = tmp_path / "run.json"
    output = cli("sessions", "export", session_id, "--format", "trajectory", "-o", str(target))
    document = json.loads(target.read_text(encoding="utf-8"))
    assert document["format"] == FORMAT
    assert document["session"]["id"] == session_id
    assert [step["role"] for step in document["steps"]] == ["user", "assistant", "tool", "assistant"]
    call = document["steps"][1]["tool_calls"][0]
    assert (call["name"], call["arguments"]) == ("read_file", {"path": "data.txt"})
    assert call["id"]
    assert document["steps"][2]["name"] == "read_file"
    assert "forty-two" in document["steps"][2]["content"]
    assert "forty-two" in document["steps"][3]["content"]
    assert "4 steps" in output


def test_the_trajectory_leaves_out_what_is_not_the_conversation():
    document = build_trajectory(
        {"id": "s1", "source": "cli", "model": "m", "provider": "p", "title": "t", "started_at": 5.0},
        [
            {"role": "system", "content": "you are an agent"},
            {"role": "user", "content": "hello", "turn_context": "<memory-context>a fact</memory-context>"},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {"id": "c1", "function": {"name": "terminal", "arguments": '{"command": "ls"}'}}
                ],
                "provider_data": {"signature": "opaque"},
                "_row_id": 7,
                "timestamp": 1.5,
            },
            {"role": "tool", "tool_call_id": "c1", "name": "terminal", "content": "a b"},
            {"role": "user", "content": "a note to myself", "display_kind": "internal"},
            {"role": "assistant", "content": "done"},
        ],
    )
    assert [step["role"] for step in document["steps"]] == ["user", "assistant", "tool", "assistant"]
    assert document["steps"][0]["context"] == "<memory-context>a fact</memory-context>"
    assert document["steps"][1]["content"] == ""
    assert document["steps"][1]["timestamp"] == 1.5
    assert document["steps"][1]["tool_calls"][0]["arguments"] == {"command": "ls"}
    text = json.dumps(document)
    assert "opaque" not in text and "provider_data" not in text and "_row_id" not in text
    assert "a note to myself" not in text and "you are an agent" not in text


def test_the_trajectory_redacts_a_credential_the_raw_export_keeps(cli, clite_home, tmp_path):
    (clite_home / ".env").write_text(f"OPENROUTER_API_KEY={SECRET}\n", encoding="utf-8")
    cli("-q", f"note my key {SECRET}")
    session_id = get_session_db().list_sessions()[0]["id"]
    trajectory = tmp_path / "trajectory.json"
    cli("sessions", "export", session_id, "--format", "trajectory", "-o", str(trajectory))
    written = trajectory.read_text(encoding="utf-8")
    assert SECRET not in written and "[REDACTED]" in written
    raw = tmp_path / "raw.json"
    cli("sessions", "export", session_id, "-o", str(raw))
    # The plain export is the stored transcript, unchanged; that is why the trajectory exists.
    assert SECRET in raw.read_text(encoding="utf-8")


def test_tool_arguments_that_are_not_json_are_kept_as_they_came():
    document = build_trajectory(
        {"id": "s1"},
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "c1", "function": {"name": "terminal", "arguments": "{oops"}}],
            }
        ],
    )
    assert document["steps"][0]["tool_calls"][0]["arguments"] == {"unparsed": "{oops"}


def test_a_secret_inside_tool_arguments_is_redacted():
    with secret_scope({"SCOPE_TEST_KEY": SECRET}):
        document = build_trajectory(
            {"id": "s1"},
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "c1",
                            "function": {"name": "terminal", "arguments": json.dumps({"cmd": SECRET})},
                        }
                    ],
                }
            ],
        )
    assert document["steps"][0]["tool_calls"][0]["arguments"] == {"cmd": "[REDACTED]"}
