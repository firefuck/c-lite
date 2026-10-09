"""Resolve CLITE_HOME for standalone skill scripts.

Skill scripts may run outside the C-lite process (system Python, nix env,
CI).  This module provides ``get_clite_home()`` and ``display_clite_home()``
so the home resolution stays in one place.
"""

from __future__ import annotations

import os
from pathlib import Path


def get_clite_home() -> Path:
    """Return the C-lite home directory (default: ``~/.clite``)."""
    val = os.environ.get("CLITE_HOME", "").strip()
    return Path(val) if val else Path.home() / ".clite"


def display_clite_home() -> str:
    """A user-friendly ``~/``-shortened display string."""
    home = get_clite_home()
    try:
        return "~/" + home.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(home)
