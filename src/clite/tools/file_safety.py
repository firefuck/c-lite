"""Write guard for the file tools.

The agent must not be able to edit its own credentials or settings: a prompt-injected page
that talks the model into ``write_file ~/.clite/.env`` or into adding itself to the command
allowlist would otherwise escalate without ever touching the terminal approval gate.
"""

from __future__ import annotations

import os
from pathlib import Path

from clite.core.constants import get_default_root, get_home

_HOME_RELATIVE_DENY = (".ssh", ".gnupg", ".aws", ".kube", ".docker/config.json", ".netrc", ".npmrc", ".pypirc")
_SYSTEM_PREFIXES = ("/etc", "/boot", "/usr", "/bin", "/sbin", "/lib", "/sys", "/proc", "/dev")
_PROTECTED_NAMES = (".env", "config.yaml", "auth.json")


def _resolve(path: str | os.PathLike[str]) -> Path:
    return Path(os.path.expanduser(str(path))).resolve(strict=False)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def write_denied_reason(path: str | os.PathLike[str]) -> str | None:
    """Why ``path`` may not be written, or ``None`` when it may."""
    target = _resolve(path)
    for home in {get_home(), get_default_root()}:
        for name in _PROTECTED_NAMES:
            if target == (home / name).resolve(strict=False):
                return f"{name} holds this agent's own credentials or settings; the user edits it, not the agent"
    user_home = Path.home()
    for relative in _HOME_RELATIVE_DENY:
        if _is_within(target, user_home / relative):
            return f"~/{relative} holds credentials"
    if os.name != "nt":
        for prefix in _SYSTEM_PREFIXES:
            if _is_within(target, Path(prefix)):
                return f"{prefix} is a system directory"
    return None
