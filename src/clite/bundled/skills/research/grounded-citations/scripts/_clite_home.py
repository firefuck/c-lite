"""Resolve CLITE_HOME for standalone skill scripts.

Skill scripts may run outside the C-lite process (system Python, nix env,
CI).  This module provides ``get_clite_home()`` so profile resolution
stays in one place.
"""

from __future__ import annotations

import os
from pathlib import Path


def get_clite_home() -> Path:
    """Return the C-lite home directory (default: ``~/.clite``)."""
    val = os.environ.get("CLITE_HOME", "").strip()
    return Path(val) if val else Path.home() / ".clite"
