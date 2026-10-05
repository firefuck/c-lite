"""Profiles: fully separate homes under ``<default root>/profiles/<name>``.

A profile has its own config, secrets, memory, sessions, skills and plugins. Profiles are
independent on purpose: there is no live inheritance from the default profile. ``clone``
copies files once, at creation.
"""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from clite.core.brand import HOME_ENV
from clite.core.constants import (
    ensure_dir,
    get_default_root,
    get_home,
    get_profiles_root,
    profile_home,
)
from clite.core.errors import ProfileError
from clite.core.io import atomic_write_text

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
# Files that define a profile's identity and are copied by ``clone``.
_CLONE_FILES = ("config.yaml", "SOUL.md")
_CLONE_DIRS = ("skills",)


@dataclass(frozen=True)
class ProfileInfo:
    name: str
    home: Path
    active: bool


def validate_profile_name(name: str) -> str:
    if name == "default":
        return name
    if not _NAME_RE.match(name):
        raise ProfileError(
            f"invalid profile name {name!r}: use lowercase letters, digits, '-' or '_' (max 32 chars)"
        )
    return name


def _active_marker() -> Path:
    return get_default_root() / "active_profile"


def get_sticky_profile() -> str:
    """The profile chosen with ``profile use``; ``default`` when none is set."""
    try:
        name = _active_marker().read_text(encoding="utf-8").strip()
    except OSError:
        return "default"
    return name or "default"


def get_active_profile_name() -> str:
    """Name of the profile the current context is running under."""
    home = get_home().expanduser().resolve(strict=False)
    profiles = get_profiles_root().expanduser().resolve(strict=False)
    try:
        relative = home.relative_to(profiles)
    except ValueError:
        return "default"
    return relative.parts[0] if relative.parts else "default"


def list_profiles() -> list[ProfileInfo]:
    active = get_active_profile_name()
    found = [ProfileInfo("default", get_default_root(), active == "default")]
    root = get_profiles_root()
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                found.append(ProfileInfo(child.name, child, active == child.name))
    return found


def profile_exists(name: str) -> bool:
    return name == "default" or profile_home(name).is_dir()


def create_profile(name: str, *, clone_from: str | None = None) -> Path:
    validate_profile_name(name)
    if name == "default":
        raise ProfileError("the default profile always exists")
    target = profile_home(name)
    if target.exists():
        raise ProfileError(f"profile {name!r} already exists")
    ensure_dir(target)
    if clone_from is not None:
        source = profile_home(clone_from)
        if not source.is_dir():
            shutil.rmtree(target, ignore_errors=True)
            raise ProfileError(f"cannot clone from unknown profile {clone_from!r}")
        # Secrets are deliberately not cloned: a second profile sharing a bot token would
        # have two gateways fighting over one connection.
        for filename in _CLONE_FILES:
            if (source / filename).is_file():
                shutil.copy2(source / filename, target / filename)
        for dirname in _CLONE_DIRS:
            if (source / dirname).is_dir():
                shutil.copytree(source / dirname, target / dirname)
    return target


def delete_profile(name: str) -> None:
    validate_profile_name(name)
    if name == "default":
        raise ProfileError("the default profile cannot be deleted")
    target = profile_home(name)
    if not target.is_dir():
        raise ProfileError(f"profile {name!r} does not exist")
    shutil.rmtree(target)
    if get_sticky_profile() == name:
        set_sticky_profile("default")


def set_sticky_profile(name: str) -> None:
    validate_profile_name(name)
    if not profile_exists(name):
        raise ProfileError(f"profile {name!r} does not exist")
    atomic_write_text(_active_marker(), name + "\n")


def apply_profile_override(argv: list[str]) -> list[str]:
    """Consume ``-p/--profile NAME`` from ``argv`` and point ``CLITE_HOME`` at that profile.

    Must run BEFORE any module reads the home: later imports resolve paths from it. An
    explicit ``CLITE_HOME`` in the environment wins over the sticky profile, and ``-p`` wins
    over both.
    """
    remaining: list[str] = []
    requested: str | None = None
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg in ("-p", "--profile") and index + 1 < len(argv):
            requested = argv[index + 1]
            index += 2
            continue
        if arg.startswith("--profile="):
            requested = arg.split("=", 1)[1]
            index += 1
            continue
        remaining.append(arg)
        index += 1
    if requested is None and not os.environ.get(HOME_ENV, "").strip():
        sticky = get_sticky_profile()
        requested = sticky if sticky != "default" else None
    if requested is not None:
        validate_profile_name(requested)
        if not profile_exists(requested):
            raise ProfileError(
                f"profile {requested!r} does not exist; create it with `profile create {requested}`"
            )
        os.environ[HOME_ENV] = str(profile_home(requested))
    return remaining
