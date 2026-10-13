"""Execution environments: the file tools and terminal work the same on every backend.

The local backend is the reference: the file tools reach their data through
``LocalEnvironment``'s operations and behave exactly as before. Docker and SSH are exercised
against their real counterpart when it exists (the ``docker`` marker skips without a daemon);
SSH has no verifiable local endpoint, so its translation is unit-tested against a fake.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from clite.tools.builtin.file_tools import patch_tool, read_file_tool, search_files_tool, write_file_tool
from clite.tools.context import ToolContext
from clite.tools.environments import (
    FileInfo,
    LocalEnvironment,
    cleanup_all_environments,
    cleanup_environment,
    environment_backends,
    get_environment,
    register_environment_backend,
)
from clite.tools.environments.base import BaseEnvironment, ExecResult


def _ctx(tmp_path, *parts: str) -> ToolContext:
    workspace = tmp_path.joinpath(*parts)
    workspace.mkdir(parents=True, exist_ok=True)
    return ToolContext(task_id="env", cwd=str(workspace))


# ── file operations on the base interface ───────────────────────────────────────────────


def test_base_environment_file_operations_are_abstract_by_default():
    """A backend must answer the four operations; the base class only declares them."""

    class Bare(BaseEnvironment):
        name = "bare"

        def execute(self, command, **kwargs):  # pragma: no cover - not run
            return ExecResult("", 0)

    environment = Bare(cwd=".")
    for call in (
        lambda: environment.read_file("x"),
        lambda: environment.write_file("x", "y"),
        lambda: environment.list_dir("."),
        lambda: environment.stat("x"),
        lambda: environment.spawn_background("true", cwd="."),
    ):
        with pytest.raises(NotImplementedError):
            call()


def test_local_environment_implements_the_file_operations(tmp_path):
    environment = LocalEnvironment(cwd=str(tmp_path))
    environment.write_file(str(tmp_path / "a.txt"), "hello\n")
    read = environment.read_file(str(tmp_path / "a.txt"))
    assert read.content == "hello\n" and read.size == 6 and not read.binary
    assert environment.stat(str(tmp_path / "a.txt")) == FileInfo(exists=True, is_file=True, size=6)
    names = {entry.name for entry in environment.list_dir(str(tmp_path))}
    assert "a.txt" in names and environment.stat(str(tmp_path / "a.txt")).is_file


def test_local_read_marks_a_binary_file(tmp_path):
    (tmp_path / "blob.bin").write_bytes(b"\x00\x01\x02")
    read = LocalEnvironment(cwd=str(tmp_path)).read_file(str(tmp_path / "blob.bin"))
    assert read.binary and read.size == 3


def test_file_tools_read_and_write_through_the_environment(tmp_path, clite_home):
    """The point of the interface: write_file/read_file answer through the backend, not pathlib."""
    ctx = _ctx(tmp_path, "ws")
    calls: list[str] = []

    class Recording(LocalEnvironment):
        name = "recording"

        def write_file(self, path, content):
            calls.append("write")
            super().write_file(path, content)

        def read_file(self, path, *, max_bytes=None):
            calls.append("read")
            return super().read_file(path, max_bytes=max_bytes)

        def list_dir(self, path):
            calls.append("list")
            return super().list_dir(path)

        def stat(self, path):
            calls.append("stat")
            return super().stat(path)

    register_environment_backend(
        "recording", lambda *, cwd="", timeout=180: Recording(cwd=cwd, timeout=timeout)
    )
    import clite.core.config as config

    (clite_home / "config.yaml").write_text("terminal:\n  backend: recording\n")
    config.reset_config_cache()
    cleanup_environment("env")

    assert json.loads(write_file_tool({"path": "x.txt", "content": "hi\n"}, ctx))["created"] is True
    assert json.loads(read_file_tool({"path": "x.txt"}, ctx))["content"] == "1|hi"
    assert json.loads(search_files_tool({"pattern": "hi"}, ctx))["count"] == 1
    assert (
        json.loads(patch_tool({"path": "x.txt", "old_string": "hi", "new_string": "bye"}, ctx))[
            "replacements"
        ]
        == 1
    )
    assert set(calls) >= {"write", "read", "list", "stat"}


def test_files_outside_the_workspace_are_readable_on_the_local_backend(tmp_path):
    """The local backend is the host filesystem: no mount, no sandbox (documented)."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("reachable\n")
    ctx = _ctx(tmp_path, "ws")
    assert "reachable" in json.loads(read_file_tool({"path": str(outside / "secret.txt")}, ctx))["content"]


# ── registry and selection ──────────────────────────────────────────────────────────────


def test_local_docker_and_ssh_are_registered_backends():
    assert {"local", "docker", "ssh"} <= set(environment_backends())


def test_the_backend_is_chosen_by_config(tmp_path, clite_home):
    import clite.core.config as config

    (clite_home / "config.yaml").write_text("terminal:\n  backend: does-not-exist\n")
    config.reset_config_cache()
    with pytest.raises(ValueError, match="unknown terminal.backend"):
        get_environment("chooser", cwd=str(tmp_path))


def test_ssh_backend_refuses_without_a_host(tmp_path):
    from clite.tools.environments.ssh import SSHEnvironment

    with pytest.raises(ValueError, match="terminal.ssh.host is empty"):
        SSHEnvironment(cwd=str(tmp_path))


def test_docker_backend_refuses_without_an_image(tmp_path):
    from clite.tools.environments.docker import DockerEnvironment

    environment = DockerEnvironment(cwd=str(tmp_path))
    result = environment.execute("echo hi")
    assert result.exit_code == 126 and "terminal.docker.image is empty" in result.output


# ── Docker (skipped without a daemon) ───────────────────────────────────────────────────


@pytest.mark.docker
@pytest.mark.platforms("linux", "macos")
def test_docker_runs_commands_in_a_container(tmp_path, clite_home):
    import clite.core.config as config

    (clite_home / "config.yaml").write_text(
        f"terminal:\n  backend: docker\n  cwd: {tmp_path}\n  docker:\n    image: alpine:3\n"
    )
    config.reset_config_cache()
    cleanup_all_environments()

    from clite.tools.builtin.terminal import terminal_tool

    ctx = ToolContext(task_id="docker-run", cwd=str(tmp_path))
    result = json.loads(terminal_tool({"command": "echo in-container"}, ctx))
    assert result["exit_code"] == 0 and "in-container" in result["output"], result["output"]
    cleanup_environment("docker-run")


@pytest.mark.docker
@pytest.mark.platforms("linux", "macos")
def test_docker_file_tools_write_through_the_mount(tmp_path, clite_home):
    import clite.core.config as config

    (clite_home / "config.yaml").write_text(
        f"terminal:\n  backend: docker\n  cwd: {tmp_path}\n  docker:\n    image: alpine:3\n"
    )
    config.reset_config_cache()
    cleanup_all_environments()

    ctx = ToolContext(task_id="docker-files", cwd=str(tmp_path))
    assert json.loads(write_file_tool({"path": "made-in-container.txt", "content": "from the mount\n"}, ctx))[
        "created"
    ]
    assert (tmp_path / "made-in-container.txt").read_text() == "from the mount\n"
    assert json.loads(read_file_tool({"path": "made-in-container.txt"}, ctx))["content"] == "1|from the mount"
    cleanup_environment("docker-files")


@pytest.mark.docker
@pytest.mark.platforms("linux", "macos")
def test_a_file_outside_the_mount_is_not_readable_from_the_container(tmp_path, clite_home):
    """The container only sees what is mounted: a file above the workspace is absent inside it."""
    import clite.core.config as config

    workspace = tmp_path / "ws"
    workspace.mkdir()
    (tmp_path / "outside-the-mount.txt").write_text("should not be visible\n")
    (clite_home / "config.yaml").write_text(
        f"terminal:\n  backend: docker\n  cwd: {workspace}\n  docker:\n    image: alpine:3\n"
    )
    config.reset_config_cache()
    cleanup_all_environments()

    ctx = ToolContext(task_id="docker-mount", cwd=str(workspace))
    outside = str(tmp_path / "outside-the-mount.txt")
    # The file tools run on the host against the mounted workspace (environments/base.py: a
    # backend that mounts a host-visible workspace inherits the local file operations), so a
    # host path above the mount is still readable through them. The container boundary is what
    # *commands* see, and that is asserted through the terminal below.
    content = json.loads(read_file_tool({"path": outside}, ctx))
    assert "should not be visible" in content["content"]

    from clite.tools.builtin.terminal import terminal_tool

    seen = json.loads(terminal_tool({"command": f"cat {outside} 2>&1 || echo MISSING"}, ctx))
    assert "MISSING" in seen["output"] or "No such file" in seen["output"]
    cleanup_environment("docker-mount")


# ── SSH translation over a fake transport (no real host) ────────────────────────────────


class _FakeSSH:
    """A stand-in filesystem the SSH backend talks to, so its translation is testable offline."""

    def __init__(self):
        self.files: dict[str, str] = {}

    def run(self, remote_command: str, *, stdin_data: bytes | None = None) -> ExecResult:
        if remote_command == "true":
            return ExecResult("", 0)
        if remote_command.startswith("cd ") and "printf" in remote_command:
            return self._list(remote_command)
        if remote_command.startswith("if [ -d "):
            return self._stat(remote_command)
        if remote_command.startswith("head -c"):
            path = remote_command.split(" ", 3)[-1].rsplit(" ", 1)[0]
            return ExecResult(self.files.get(path, ""), 0)
        if remote_command.startswith("base64"):
            import base64

            path = remote_command.split(" ", 1)[1].strip("'")
            return ExecResult(base64.b64encode(self.files.get(path, "").encode()).decode(), 0)
        if "base64 -d" in remote_command and stdin_data is not None:
            import base64

            path = remote_command.rsplit(" ", 1)[-1].strip("'")
            raw = stdin_data if isinstance(stdin_data, bytes) else stdin_data.encode()
            self.files[path] = base64.b64decode(raw).decode()
            return ExecResult("", 0)
        return ExecResult("", 0)

    def _list(self, command: str) -> ExecResult:
        import shlex

        directory = shlex.split(command.split("for f in", 1)[0].replace("cd", "").strip())[0]
        lines = [
            f"clite-ls-entry\tf\t{name.rsplit('/', 1)[-1]}\t{len(self.files[name])}"
            for name in sorted(self.files)
            if name.rsplit("/", 1)[0] == directory
        ]
        return ExecResult("\n".join(lines), 0)

    def _stat(self, command: str) -> ExecResult:
        import shlex

        words = shlex.split(command.replace(";", " ").replace("[", " ").replace("]", " "))
        path = next((word for word in words if "/" in word), "")
        if path not in self.files:
            return ExecResult("missing", 0)
        return ExecResult(f"file\n{len(self.files[path])}", 0)


@pytest.fixture
def fake_ssh(monkeypatch):
    from clite.tools.environments import ssh as ssh_module

    fake = _FakeSSH()
    monkeypatch.setattr(
        ssh_module.SSHEnvironment,
        "_run_ssh",
        lambda self, command, timeout=60, stdin_data=None: fake.run(command, stdin_data=stdin_data),
    )
    monkeypatch.setattr(
        ssh_module.SSHEnvironment,
        "execute",
        lambda self, command, **kwargs: fake.run(command, stdin_data=None),
    )
    return fake


def test_ssh_environment_translates_file_operations(tmp_path, clite_home, fake_ssh):
    """With the transport faked, the SSH backend's read/write/list/stat mirror the local ones."""
    import clite.core.config as config

    (clite_home / "config.yaml").write_text("terminal:\n  ssh:\n    host: build@box\n")
    config.reset_config_cache()

    from clite.tools.environments.ssh import SSHEnvironment

    environment = SSHEnvironment(cwd="/srv/app")
    fake_ssh.files["/srv/app/notes.txt"] = "line one\nline two\n"

    assert environment.read_file("/srv/app/notes.txt").content == "line one\nline two\n"
    assert environment.stat("/srv/app/notes.txt").is_file
    assert not environment.stat("/srv/app/missing.txt").exists
    names = {entry.name for entry in environment.list_dir("/srv/app")}
    assert names == {"notes.txt"}
    environment.write_file("/srv/app/new.txt", "written")
    assert fake_ssh.files["/srv/app/new.txt"] == "written"


def test_ssh_resolve_path_joins_the_remote_cwd(tmp_path):
    from clite.tools.environments.ssh import SSHEnvironment

    environment = SSHEnvironment.__new__(SSHEnvironment)
    environment.cwd = "/srv/app"
    assert environment.resolve_path("sub/x.txt") == "/srv/app/sub/x.txt"
    assert environment.resolve_path("/abs/x.txt") == "/abs/x.txt"


def test_docker_client_environment_keeps_only_docker_settings(monkeypatch):
    """The docker CLI gets its own DOCKER_* settings; a provider key must not ride along."""
    from clite.tools.environments.docker import _docker_client_env

    monkeypatch.setenv("OPENAI_API_KEY", "«redacted:sk-…»")
    monkeypatch.setenv("DOCKER_HOST", "tcp://127.0.0.1:2375")
    env = _docker_client_env()
    assert env.get("DOCKER_HOST") == "tcp://127.0.0.1:2375"
    assert "OPENAI_API_KEY" not in env


def test_docker_cleanup_is_a_noop_without_a_container(tmp_path):
    from clite.tools.environments.docker import DockerEnvironment

    environment = DockerEnvironment(cwd=str(tmp_path))
    environment.cleanup()  # no container yet: nothing to remove, no error


@pytest.mark.skipif(os.name == "nt", reason="posix-only helper")
def test_kill_process_tree_is_reused_from_local():
    """Background processes on every backend reuse the same process-group kill."""
    from clite.tools.environments.local import kill_process_tree

    process = subprocess.Popen(["sleep", "30"], start_new_session=True)
    kill_process_tree(process)
    assert process.wait(2.0) is not None


# ── SSH live tests (local loopback; opt in with -m ssh) ───────────────────────────────


_LIVE_SSH_KEY = Path("/root/.ssh/id_ed25519_test")


def _configure_live_ssh(clite_home) -> None:
    import clite.core.config as config

    try:
        if not _LIVE_SSH_KEY.is_file():
            pytest.skip(f"live SSH key {_LIVE_SSH_KEY} not present")
        _LIVE_SSH_KEY.read_bytes()
    except (PermissionError, OSError):
        pytest.skip(f"live SSH key {_LIVE_SSH_KEY} not accessible by current user")

    (clite_home / "config.yaml").write_text(
        f"terminal:\n  ssh:\n    host: root@localhost\n    key: {_LIVE_SSH_KEY}\n"
    )
    config.reset_config_cache()


@pytest.mark.ssh
@pytest.mark.platforms("linux", "macos")
def test_ssh_runs_commands_over_a_real_connection(tmp_path, clite_home):
    from clite.tools.environments.ssh import SSHEnvironment

    _configure_live_ssh(clite_home)
    environment = SSHEnvironment(cwd=str(tmp_path))
    try:
        result = environment.execute("printf hello-ssh-live", timeout=30)
    finally:
        environment.cleanup()

    assert result.exit_code == 0
    assert result.output == "hello-ssh-live"


@pytest.mark.ssh
@pytest.mark.platforms("linux", "macos")
def test_ssh_read_and_write_files_over_a_real_connection(tmp_path, clite_home):
    from clite.tools.environments.ssh import SSHEnvironment

    _configure_live_ssh(clite_home)
    environment = SSHEnvironment(cwd=str(tmp_path))
    remote_file = str(tmp_path / "greeting.txt")
    try:
        environment.write_file(remote_file, "hello from SSH live test\n")
        result = environment.read_file(remote_file)
        names = {entry.name for entry in environment.list_dir(str(tmp_path))}
        info = environment.stat(remote_file)
    finally:
        environment.cleanup()

    assert result.content == "hello from SSH live test\n"
    assert "greeting.txt" in names
    assert info.is_file and info.exists


@pytest.mark.ssh
@pytest.mark.platforms("linux", "macos")
def test_ssh_execute_uses_the_configured_remote_cwd(tmp_path, clite_home):
    from clite.tools.environments.ssh import SSHEnvironment

    _configure_live_ssh(clite_home)
    environment = SSHEnvironment(cwd=str(tmp_path))
    try:
        result = environment.execute("pwd", timeout=30)
    finally:
        environment.cleanup()

    assert result.exit_code == 0
    assert result.output.strip() == str(tmp_path)
