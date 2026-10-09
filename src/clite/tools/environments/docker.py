"""Docker execution: one container per ``task_id``, the working directory bind-mounted in.

The container is the boundary the roadmap promises over "no sandbox": the agent's commands,
and therefore its file tools, run with the container's filesystem and user, not the host's.
The host working directory is mounted at the same path inside the container, so
``resolve_path`` is identity and the file tools (which run on the host against that mount)
see exactly the files the container does. Credentials are not passed in: the container starts
with a bare environment, and nothing from the host's ``.env`` or provider keys crosses over.

Config:

* ``terminal.docker.image``   — image to run (required to use the backend)
* ``terminal.docker.mounts``  — extra ``-v host:container[:mode]`` entries
* ``terminal.docker.network`` — Docker network name (default ``none``: no network)
* ``terminal.docker.user``    — user inside the container (default the image's own)
* ``terminal.docker.memory``  — memory limit, e.g. ``"2g"``
* ``terminal.docker.keep_container`` — leave the container running after ``cleanup``
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
import uuid
from collections.abc import Callable

from clite.core.config import config_get
from clite.core.threads import start_thread
from clite.tools.environments.base import ExecResult
from clite.tools.environments.local import _POLL_SECONDS, LocalEnvironment, read_output_chunks


class DockerEnvironment(LocalEnvironment):
    """Run commands inside a container; file operations use the bind-mounted workspace.

    It reuses ``LocalEnvironment`` for the file tools because the workspace is mounted at the
    same path — the difference between this and ``local`` is entirely *where commands run*.
    """

    name = "docker"

    def __init__(self, cwd: str = "", *, timeout: int = 180) -> None:
        super().__init__(cwd or os.getcwd(), timeout=timeout)
        self._container_id: str | None = None

    # ── container lifecycle ──────────────────────────────────────────────────────────────

    def _ensure_container(self) -> str:
        if self._container_id is not None:
            return self._container_id
        image = str(config_get("terminal.docker.image", "") or "").strip()
        if not image:
            raise RuntimeError(
                "terminal.docker.image is empty; set it in config.yaml "
                "(e.g. `terminal.docker.image: python:3.12-slim`) to use the Docker backend"
            )
        name = "clite-" + uuid.uuid4().hex[:12]
        argv = ["docker", "run", "-d", "--name", name]
        for mount in config_get("terminal.docker.mounts", []) or []:
            argv += ["-v", str(mount)]
        # The workspace itself is mounted so the file tools and the container agree on paths.
        argv += ["-v", f"{self.cwd}:{self.cwd}"]
        user = str(config_get("terminal.docker.user", "") or "")
        if user:
            argv += ["--user", user]
        memory = str(config_get("terminal.docker.memory", "") or "")
        if memory:
            argv += ["--memory", memory]
        argv += ["--network", str(config_get("terminal.docker.network", "none") or "none")]
        # No --workdir here: the image's filesystem usually lacks the host working directory, and
        # a missing working directory refuses to start the container. The mount above creates the
        # path, and every exec below passes -w explicitly; the mkdir keeps a fresh image whose
        # filesystem lacks the path working before that mount lands.
        argv += [
            "--entrypoint",
            "/bin/sh",
            image,
            "-c",
            'mkdir -p "$1" && exec sleep infinity',
            "sh",
            self.cwd,
        ]
        result = self._run_docker(argv)
        if result.exit_code != 0:
            raise RuntimeError(f"could not start Docker container: {result.output.strip()}")
        # Address the container by the name we chose, not by parsing run's output: a first-time
        # image pull interleaves progress lines ("Status: Downloaded newer image for ...") with
        # the id, so the last line of merged output is not reliably the id.
        self._container_id = name
        return self._container_id

    def _run_docker(self, argv: list[str], *, timeout: int = 60) -> ExecResult:
        try:
            completed = subprocess.run(  # noqa: S603 - managing the container is this backend's job
                argv,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=_docker_client_env(),
            )
        except FileNotFoundError:
            return ExecResult("docker is not installed or not on PATH", 127)
        except subprocess.TimeoutExpired:
            return ExecResult(f"docker command timed out after {timeout}s", 124, timed_out=True)
        return ExecResult(completed.stdout + completed.stderr, completed.returncode)

    def cleanup(self) -> None:
        """Stop and remove the container unless the user asked to keep it."""
        container, self._container_id = self._container_id, None
        if container is None or config_get("terminal.docker.keep_container", False):
            return
        self._run_docker(["docker", "rm", "-f", container], timeout=30)

    # ── command execution ────────────────────────────────────────────────────────────────

    def spawn_background(self, command: str, *, cwd: str) -> object:
        """Run the command in the container detached, keeping a ``docker exec`` client open
        so the ``process`` tool can still read its output, feed stdin and kill it."""
        container = self._ensure_container()
        workdir = self.resolve_path(cwd)
        argv = ["docker", "exec", "-i", "-w", workdir, container, "/bin/sh", "-c", command]
        return subprocess.Popen(  # noqa: S603
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_docker_client_env(),
        )

    def execute(
        self,
        command: str,
        *,
        cwd: str | None = None,
        timeout: int | None = None,
        stdin_data: str | None = None,
        interrupt: threading.Event | None = None,
        on_output: Callable[[str], None] | None = None,
        max_output_chars: int | None = None,
    ) -> ExecResult:
        try:
            container = self._ensure_container()
        except RuntimeError as exc:
            return ExecResult(str(exc), 126)
        workdir = self.resolve_path(cwd) if cwd else self.cwd
        limit = 50_000 if max_output_chars is None else max(0, max_output_chars)
        deadline = time.monotonic() + (timeout or self.default_timeout)

        argv = ["docker", "exec", "-i", "-w", workdir, container, "/bin/sh", "-c", command]
        try:
            process = subprocess.Popen(  # noqa: S603
                argv,
                stdin=subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=_docker_client_env(),
            )
        except OSError as exc:
            return ExecResult(f"could not run docker exec: {exc}", 126)

        chunks: list[str] = []
        size = 0
        truncated = False

        def collect() -> None:
            nonlocal size, truncated
            assert process.stdout is not None
            for chunk in read_output_chunks(process.stdout):
                if on_output is not None:
                    try:
                        on_output(chunk)
                    except Exception:  # noqa: BLE001 - a display callback must not kill the reader
                        pass
                retained = chunk[: max(0, limit - size)]
                if retained:
                    chunks.append(retained)
                    size += len(retained)
                if len(retained) < len(chunk):
                    truncated = True

        reader_thread = start_thread(collect, name="clite-docker-reader")
        if stdin_data is not None and process.stdin is not None:
            try:
                process.stdin.write(stdin_data)
                process.stdin.close()
            except OSError:
                pass
        timed_out = interrupted = False
        while process.poll() is None:
            if interrupt is not None and interrupt.is_set():
                interrupted = True
                break
            if time.monotonic() > deadline:
                timed_out = True
                break
            time.sleep(_POLL_SECONDS)
        if timed_out or interrupted:
            # Killing the docker client stops waiting on the command; the container keeps its
            # state and is removed when the session closes.
            process.kill()
            try:
                process.wait(2.0)
            except subprocess.TimeoutExpired:
                pass
        reader_thread.join(timeout=2.0)

        output = "".join(chunks)
        if truncated:
            output += f"\n[output truncated at {limit} characters]"
        exit_code = process.returncode if process.returncode is not None else -1
        if timed_out:
            output += f"\n[command timed out after {timeout or self.default_timeout}s and was killed]"
            exit_code = 124
        elif interrupted:
            output += "\n[command interrupted]"
            exit_code = 130
        return ExecResult(output, exit_code, timed_out, interrupted, truncated)


def _docker_client_env() -> dict[str, str]:
    """Environment for the Docker *client* only.

    The client may need the host's ``DOCKER_*`` settings to reach the daemon, so those names
    pass through. Nothing from ``.env`` or a provider key is added: whatever reaches the
    container comes solely from ``terminal.docker.mounts`` or an explicit ``--env``.
    """
    keep = {"DOCKER_HOST", "DOCKER_CONFIG", "DOCKER_CONTEXT", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH"}
    env = {key: value for key, value in os.environ.items() if key in keep}
    env.setdefault("PATH", os.environ.get("PATH", ""))
    return env


def docker_factory(*, cwd: str = "", timeout: int = 180) -> DockerEnvironment:
    return DockerEnvironment(cwd=cwd, timeout=timeout)
