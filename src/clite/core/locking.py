"""Cross-process file locks that lock on POSIX and on Windows.

``exclusive_lock(path)`` blocks until this process holds the lock on ``path``. ``fcntl.flock``
is used on POSIX and ``msvcrt.locking`` on Windows. The operating system releases the lock when
the process exits, so a crash never leaves a stale lock behind. The lock file is kept, not
deleted: every process must lock the same file.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

# msvcrt.locking(LK_LOCK) gives up after ten one-second tries; poll instead, without a limit.
_WINDOWS_POLL_SECONDS = 0.05


@contextlib.contextmanager
def exclusive_lock(path: str | Path) -> Iterator[None]:
    """Hold an exclusive lock on ``path`` (created when missing) for the ``with`` block."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(target, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        _acquire(fd)
        try:
            yield
        finally:
            _release(fd)
    finally:
        os.close(fd)


def _acquire(fd: int) -> None:
    if sys.platform == "win32":
        while True:
            os.lseek(fd, 0, os.SEEK_SET)
            try:
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(_WINDOWS_POLL_SECONDS)
    else:
        fcntl.flock(fd, fcntl.LOCK_EX)


def _release(fd: int) -> None:
    if sys.platform == "win32":
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
