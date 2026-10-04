"""Profile-aware home resolution. Import-safe and stdlib-only.

Resolution order for the active home: context-local override, then the ``CLITE_HOME``
environment variable, then the platform default (``~/.clite``).

Two rules every caller follows:

* Never hardcode ``~/.clite``. Use :func:`get_home` for paths and :func:`display_home` for
  text shown to the user.
* Never keep a home-derived path in a module-level constant. One process may serve several
  profiles, and a constant freezes to whichever profile was active at import time.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path

from clite.core.brand import HOME_DIRNAME, HOME_ENV

_UNSET = object()
_HOME_OVERRIDE: ContextVar[object] = ContextVar("clite_home_override", default=_UNSET)


def set_home_override(path: str | Path | None) -> Token:
    """Bind a context-local home and return the reset token.

    Deliberately leaves ``os.environ`` alone: the environment is shared by every thread,
    while a ContextVar follows the task or thread that set it.
    """
    return _HOME_OVERRIDE.set(_UNSET if path is None else str(path))


def reset_home_override(token: Token) -> None:
    _HOME_OVERRIDE.reset(token)


def get_home_override() -> str | None:
    value = _HOME_OVERRIDE.get()
    return str(value) if value is not _UNSET and value else None


@contextmanager
def home_scope(path: str | Path) -> Iterator[Path]:
    """Run a block with ``path`` as the active home (profile scope for one activity)."""
    token = set_home_override(path)
    try:
        yield Path(path)
    finally:
        reset_home_override(token)


def _expand(path: str) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(path)))


def get_default_root() -> Path:
    """The default profile's home, ignoring overrides and ``CLITE_HOME``.

    Profiles live under ``<default root>/profiles/<name>``, so profile management anchors
    here: ``clite -p work profile list`` must still see every profile.
    """
    if sys.platform == "win32":
        local = os.environ.get("LOCALAPPDATA", "").strip()
        base = Path(local) if local else Path.home() / "AppData" / "Local"
        return base / HOME_DIRNAME.lstrip(".")
    return Path.home() / HOME_DIRNAME


def get_process_home() -> Path:
    """The home this process was launched with: ``CLITE_HOME`` or the default root."""
    env = os.environ.get(HOME_ENV, "").strip()
    return _expand(env) if env else get_default_root()


def get_home() -> Path:
    """The active home: context-local override, then ``CLITE_HOME``, then the default."""
    override = get_home_override()
    return _expand(override) if override else get_process_home()


def home_key(path: str | Path | None = None) -> str:
    """Stable key for a home directory, for per-profile caches and registries."""
    candidate = Path(path) if path is not None else get_home()
    return os.path.normcase(str(candidate.expanduser().resolve(strict=False)))


def display_home(home: Path | None = None) -> str:
    """The home as the user should read it, with the user's home directory shown as ``~``."""
    target = (home or get_home()).expanduser()
    try:
        return "~/" + target.relative_to(Path.home()).as_posix()
    except ValueError:
        return str(target)


def ensure_dir(path: str | Path) -> Path:
    """``mkdir -p`` and return the path."""
    target = Path(path)
    target.mkdir(parents=True, exist_ok=True)
    return target


# ── well-known locations, all resolved at call time ──────────────────────────────────────


def get_config_path() -> Path:
    return get_home() / "config.yaml"


def get_env_path() -> Path:
    return get_home() / ".env"


def get_state_db_path() -> Path:
    return get_home() / "state.db"


def get_skills_dir() -> Path:
    return get_home() / "skills"


def get_plugins_dir() -> Path:
    return get_home() / "plugins"


def get_memories_dir() -> Path:
    return get_home() / "memories"


def get_logs_dir() -> Path:
    return get_home() / "logs"


def get_cron_dir() -> Path:
    return get_home() / "cron"


def get_cache_dir() -> Path:
    return get_home() / "cache"


def get_soul_path() -> Path:
    return get_home() / "SOUL.md"


def get_profiles_root() -> Path:
    return get_default_root() / "profiles"


def profile_home(name: str) -> Path:
    """Home directory of a named profile; ``default`` is the default root itself."""
    return get_default_root() if name in ("", "default") else get_profiles_root() / name


def bundled_dir() -> Path:
    """Directory of files shipped inside the package (bundled plugins and skills)."""
    return Path(__file__).resolve().parent.parent / "bundled"
