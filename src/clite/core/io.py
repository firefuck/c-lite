"""Atomic file writes. A crash mid-write must never leave a half-written state file."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


def _restrict_private_file(path: str) -> None:
    """Restrict to the owner: mode 0600 on POSIX, a protected owner-only DACL on NTFS."""
    if sys.platform != "win32":
        os.chmod(path, 0o600)
        return
    import ctypes
    from ctypes import wintypes

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
    convert.restype = wintypes.BOOL
    apply = advapi.SetFileSecurityW
    apply.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p]
    apply.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    descriptor = ctypes.c_void_p()
    # OW is the Owner Rights SID. No inherited ACEs: only the file owner gets full access.
    if not convert("D:P(A;;FA;;;OW)", 1, ctypes.byref(descriptor), None):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not apply(path, 0x80000004, descriptor):  # PROTECTED_DACL | DACL_SECURITY_INFORMATION
            raise ctypes.WinError(ctypes.get_last_error())
    finally:
        kernel.LocalFree(descriptor)


def atomic_write_text(path: str | Path, text: str, *, mode: int | None = None) -> None:
    """Write ``text`` to ``path`` through a temp file in the same directory and ``os.replace``."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if mode == 0o600:
                _restrict_private_file(tmp_name)
            elif mode is not None:
                os.chmod(tmp_name, mode)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def atomic_write_json(
    path: str | Path, data: Any, *, indent: int | None = 2, mode: int | None = None
) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=indent) + "\n", mode=mode)


def read_json(path: str | Path, default: Any = None) -> Any:
    """Parsed JSON, or ``default`` when the file is missing or unreadable."""
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default
