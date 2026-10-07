"""``core.locking``: one lock that really excludes another process, on POSIX and on Windows."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("store,lock_name", [("memory", ".lock"), ("cron", ".jobs.lock")])
def test_store_mutations_wait_for_another_process_lock(tmp_path, store, lock_name):
    directory = tmp_path / store
    script = (
        "import sys\nfrom pathlib import Path\n"
        "from clite.agent.memory.store import MemoryStore\n"
        "from clite.cron.jobs import JobStore\n"
        "print('ready', flush=True)\nsys.stdin.readline()\n"
        "if sys.argv[1] == 'memory':\n"
        "    assert MemoryStore(directory=Path(sys.argv[2])).add('memory', 'child note')['success']\n"
        "else:\n"
        "    JobStore(directory=Path(sys.argv[2])).create('child job', 'every 1h')\n"
        "print('written', flush=True)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", script, store, str(directory)],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", env=_child_env())
    with ThreadPoolExecutor(max_workers=1) as pool:
        try:
            assert pool.submit(child.stdout.readline).result(timeout=20).strip() == "ready"
            with exclusive_lock(directory / lock_name):
                child.stdin.write("go\n")
                child.stdin.flush()
                written = pool.submit(child.stdout.readline)
                with pytest.raises(TimeoutError):
                    written.result(timeout=1)
                assert not (directory / ("MEMORY.md" if store == "memory" else "jobs.json")).exists()
            assert written.result(timeout=20).strip() == "written"
            assert child.wait(timeout=10) == 0, child.stderr.read()
        finally:
            child.kill()
            child.wait(timeout=10)


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
