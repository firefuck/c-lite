"""Path guards for the file tools.

The agent must not be able to edit its own credentials or settings: a prompt-injected page
that talks the model into ``write_file ~/.clite/.env`` or into adding itself to the command
allowlist would otherwise escalate without ever touching the terminal approval gate.

Reading is guarded more narrowly: only files whose whole purpose is to hold credentials.
Whatever the model reads is sent to the model provider and stored in the session database.
"""

from __future__ import annotations

import os
from pathlib import Path

from clite.core.constants import get_default_root, get_home, get_profiles_root

_HOME_RELATIVE_DENY = (".ssh", ".gnupg", ".aws", ".kube", ".docker/config.json", ".netrc", ".npmrc", ".pypirc")
_SYSTEM_PREFIXES = ("/etc", "/boot", "/usr", "/bin", "/sbin", "/lib", "/sys", "/proc", "/dev")
# Files in each of the agent's homes that hold its credentials and its policy, as paths inside
# that home. config.yaml *is* the approval policy (mode, allowlist, enabled plugins),
# shell-hooks-allowlist.json records which shell hooks the user consented to run, and
# gateway/pairing.json records which chat users may talk to the agent. The command approval
# gate guards the same list.
PROTECTED_PATHS = (".env", "config.yaml", "auth.json", "shell-hooks-allowlist.json", "gateway/pairing.json")
# The subset that holds secrets. config.yaml references secrets by name only.
_CREDENTIAL_PATHS = (".env", "auth.json")


def _resolve(path: str | os.PathLike[str]) -> Path:
    return Path(os.path.expanduser(str(path))).resolve(strict=False)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent.resolve(strict=False))
        return True
    except ValueError:
        return False


def protected_path(path: str | os.PathLike[str]) -> str | None:
    """Which protected file ``path`` is, as its path inside the home it belongs to, or ``None``.

    Every home counts: the active one, the default one, and each profile's, whether or not
    that profile exists yet. Names are compared without regard to case, because the common
    macOS and Windows file systems do the same.
    """
    target = _resolve(path)
    inside = []
    for home in {get_home(), get_default_root()}:
        if _is_within(target, home):
            inside.append(target.relative_to(home.resolve(strict=False)).parts)
    if _is_within(target, get_profiles_root()):
        inside.append(target.relative_to(get_profiles_root().resolve(strict=False)).parts[1:])
    names = {"/".join(parts).lower() for parts in inside}
    return next((name for name in PROTECTED_PATHS if name in names), None)


def write_denied_reason(path: str | os.PathLike[str]) -> str | None:
    """Why ``path`` may not be written, or ``None`` when it may."""
    target = _resolve(path)
    name = protected_path(target)
    if name is not None:
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


def read_denied_reason(path: str | os.PathLike[str]) -> str | None:
    """Why ``path`` may not be read by the file tools, or ``None`` when it may."""
    target = _resolve(path)
    name = protected_path(target)
    if name in _CREDENTIAL_PATHS:
        return f"{name} holds this agent's credentials"
    user_home = Path.home()
    for relative in _HOME_RELATIVE_DENY:
        if _is_within(target, user_home / relative):
            return f"~/{relative} holds credentials"
    return None
