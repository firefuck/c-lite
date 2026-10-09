"""System-service lifecycle for the gateway."""

from __future__ import annotations

import threading

import pytest

from clite.gateway.service import GatewayLock, GatewayService, render_launch_agent, render_systemd_unit


def test_service_files_name_default_and_named_profiles():
    unit = render_systemd_unit("/usr/bin/clite", "default")
    plist = render_launch_agent("/usr/bin/clite", "work")

    assert "ExecStart=/usr/bin/clite -m clite gateway run" in unit
    assert "Restart=on-failure" in unit
    assert "Description=C-lite gateway (default)" in unit
    assert "<string>-p</string>" in plist and "<string>work</string>" in plist
    assert "com.clite.gateway.work" in plist
    assert "<string>gateway</string>" in plist and "<string>run</string>" in plist


@pytest.mark.platforms("posix")
def test_second_gateway_for_the_same_home_is_refused(tmp_path):
    first = GatewayLock(tmp_path)
    second = GatewayLock(tmp_path)

    first.acquire()
    try:
        with pytest.raises(RuntimeError, match="already running"):
            second.acquire()
    finally:
        first.release()


class _SlowRunner:
    def __init__(self) -> None:
        self.running = False
        self.accepting = True
        self.busy = True
        self.stopped = False
        self.started = threading.Event()
        self.draining = threading.Event()

    def start(self):
        self.running = True
        self.started.set()
        return ["local"]

    def begin_drain(self) -> None:
        self.accepting = False
        self.draining.set()

    def has_active_turns(self) -> bool:
        return self.busy

    def stop(self) -> None:
        self.stopped = True
        self.running = False


@pytest.mark.platforms("posix")
def test_sigterm_drains_an_active_turn_before_exiting_zero(tmp_path):
    runner = _SlowRunner()
    service = GatewayService(runner=runner, home=tmp_path, drain_timeout=1)
    result: list[int] = []

    thread = threading.Thread(target=lambda: result.append(service.run()))
    thread.start()
    assert runner.started.wait(1)
    service.request_stop()
    assert runner.draining.wait(1)
    assert thread.is_alive() and not runner.accepting and not runner.stopped
    runner.busy = False
    thread.join(1)

    assert result == [0]
    assert runner.stopped
