"""System-service lifecycle for the gateway."""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from pathlib import Path
from typing import Any

from clite.core.brand import APP_NAME
from clite.core.constants import ensure_dir, get_home
from clite.core.profiles import get_active_profile_name

_SERVICE_NAME = "clite-gateway"


def service_name(profile: str) -> str:
    """Return the platform-neutral user service name for one profile."""
    return _SERVICE_NAME if profile == "default" else f"{_SERVICE_NAME}-{profile}"


def _profile_args(profile: str) -> list[str]:
    return [] if profile == "default" else ["-p", profile]


def render_systemd_unit(executable: str, profile: str) -> str:
    """Render the per-user systemd unit for one profile."""
    command = " ".join([executable, "-m", "clite", *_profile_args(profile), "gateway", "run"])
    return f"""[Unit]
Description=C-lite gateway ({profile})
After=network-online.target

[Service]
Type=simple
ExecStart={command}
Restart=on-failure
RestartSec=5
KillSignal=SIGTERM
TimeoutStopSec=120

[Install]
WantedBy=default.target
"""


def render_launch_agent(executable: str, profile: str) -> str:
    """Render the LaunchAgent plist for one profile."""
    args = "\n".join(
        f"        <string>{item}</string>" for item in [executable, "-m", "clite", *_profile_args(profile), "gateway", "run"]
    )
    label = f"com.{APP_NAME}.gateway{'' if profile == 'default' else '.' + profile}"
    return f"""<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" \"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">
<plist version=\"1.0\">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{args}
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
"""


def service_path(profile: str | None = None) -> Path:
    """Return the current platform's generated service file path."""
    profile = profile or get_active_profile_name()
    if sys.platform == "darwin":
        suffix = "" if profile == "default" else f".{profile}"
        return Path.home() / "Library" / "LaunchAgents" / f"com.{APP_NAME}.gateway{suffix}.plist"
    return Path.home() / ".config" / "systemd" / "user" / f"{service_name(profile)}.service"


def install(executable: str) -> Path:
    """Write the user service definition for the active profile."""
    profile = get_active_profile_name()
    path = service_path(profile)
    ensure_dir(path.parent)
    content = render_launch_agent(executable, profile) if sys.platform == "darwin" else render_systemd_unit(executable, profile)
    path.write_text(content, encoding="utf-8")
    return path


def uninstall() -> Path:
    """Remove the active profile's generated service definition if present."""
    path = service_path()
    path.unlink(missing_ok=True)
    return path


class GatewayLock:
    """An advisory process lock scoped to exactly one C-lite home."""

    def __init__(self, home: Path | None = None) -> None:
        self.path = ensure_dir(ensure_dir(home or get_home()) / "gateway") / ".service.lock"
        self._fd: int | None = None

    def acquire(self) -> None:
        if self._fd is not None:
            return
        import fcntl

        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise RuntimeError("A gateway is already running for this home; use `clite gateway status`.") from None
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None


class GatewayService:
    """Own a runner, drain active turns after SIGTERM, then stop it."""

    def __init__(self, *, runner: Any, home: Path | None = None, drain_timeout: float = 110) -> None:
        self.runner = runner
        self.lock = GatewayLock(home)
        self.drain_timeout = drain_timeout
        self._stop = threading.Event()
        self._exit_code = 0
        if hasattr(self.runner, "on_restart"):
            self.runner.on_restart = self.request_restart

    def request_stop(self, *_args: Any) -> None:
        self._stop.set()

    def request_restart(self, *_args: Any) -> None:
        self._exit_code = 75  # EX_TEMPFAIL; non-zero exit code triggers Restart=on-failure
        self._stop.set()

    def run(self) -> int:
        self.lock.acquire()
        try:
            if not self.runner.start():
                return 1
            while not self._stop.wait(0.2):
                pass
            self.runner.begin_drain()
            deadline = time.monotonic() + self.drain_timeout
            while self.runner.has_active_turns() and time.monotonic() < deadline:
                self._stop.wait(0.1)
            if self.runner.has_active_turns():
                self.runner.notify_interrupted_turns()
            self.runner.stop()
            return self._exit_code
        finally:
            self.lock.release()


def run_service(runner: Any, *, drain_timeout: float = 110) -> int:
    """Run a gateway with SIGTERM/SIGINT draining support in the main thread."""
    service = GatewayService(runner=runner, drain_timeout=drain_timeout)
    previous = {sig: signal.signal(sig, service.request_stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        return service.run()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
