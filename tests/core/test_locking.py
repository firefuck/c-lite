"""``core.locking``: one lock that really excludes another process, on POSIX and on Windows."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from clite.core.locking import exclusive_lock

_HOLDER = (
    "import sys\n"
    "from clite.core.locking import exclusive_lock\n"
    "with exclusive_lock(sys.argv[1]):\n"
    "    print('held', flush=True)\n"
    "    sys.stdin.readline()\n"
)


def _child_env() -> dict[str, str]:
    env = os.environ.copy()
    src = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [src, env.get("PYTHONPATH", "")]))
    return env


def test_a_lock_held_by_another_process_blocks_until_that_process_lets_go(tmp_path):
    path = tmp_path / "state" / ".lock"
    holder = subprocess.Popen([sys.executable, "-c", _HOLDER, str(path)], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True, env=_child_env())
    acquired = threading.Event()

    def contend() -> None:
        with exclusive_lock(path):
            acquired.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        try:
            assert holder.stdout is not None and holder.stdin is not None
            assert pool.submit(holder.stdout.readline).result(timeout=20).strip() == "held"
            contender = pool.submit(contend)
            assert not acquired.wait(1.0), "the lock was taken while another process held it"
            holder.stdin.write("\n")
            holder.stdin.flush()
            contender.result(timeout=20)
            assert acquired.is_set()
        finally:
            holder.kill()
            holder.wait(timeout=10)


def test_a_process_that_dies_holding_the_lock_does_not_leave_it_stuck(tmp_path):
    path = tmp_path / ".lock"
    holder = subprocess.Popen([sys.executable, "-c", _HOLDER, str(path)], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, text=True, env=_child_env())
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert holder.stdout is not None
        assert pool.submit(holder.stdout.readline).result(timeout=20).strip() == "held"
        holder.kill()
        holder.wait(timeout=10)

        def take() -> bool:
            with exclusive_lock(path):
                return True

        assert pool.submit(take).result(timeout=20)
    assert path.exists()  # kept so every process keeps locking the same file
