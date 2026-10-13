"""Whether a command reaches for the agent's own settings or credentials.

The agent's ``config.yaml`` is its policy (approval mode, allowlist, enabled plugins) and its
``.env`` holds its credentials, so a command that reaches for them, or for any other file in
``PROTECTED_PATHS``, or that runs the agent's own management command line, can remove a gate or
leak a key. Every home of the agent counts: the active one, the default root, and each
profile's. Such a command matches ``SELF_ACCESS``, whose key is in ``NEVER_REMEMBERED``: the
user is asked every time, the answer is never remembered, and the smart reviewer never clears
it.
"""

from __future__ import annotations

import fnmatch
import functools
import logging
import posixpath
import re
from pathlib import Path

from clite.core.brand import APP_NAME, DISPLAY_NAME, HOME_DIRNAME, HOME_ENV
from clite.core.constants import get_default_root, get_home, get_profiles_root
from clite.tools.command_patterns import DangerMatch
from clite.tools.file_safety import PROTECTED_PATHS
from clite.tools.shell_reading import (
    QUOTES,
    CommandTooComplexError,
    arguments_of,
    code_payloads,
    expand_variables,
    guard_parse_limits,
    normalize_command,
    shell_plain,
    simple_commands,
    variable_values,
)

# One logger for the whole approval gate, whichever of its modules writes the record.
logger = logging.getLogger("clite.tools.approval")

SELF_ACCESS = DangerMatch("agent_settings_access", "reaches for this agent's own settings or credentials")
# Keys the user is asked about every time: never remembered for the session, never put on the
# allowlist, never cleared by the smart reviewer. Editing the policy is how a gate gets removed.
NEVER_REMEMBERED = frozenset({SELF_ACCESS.key})

_PROTECTED_NAME = re.compile(
    r"(?<![\w.\-])(?:"
    + "|".join(
        re.escape(posixpath.basename(name))
        for name in PROTECTED_PATHS
        if "." in posixpath.basename(name) or name.startswith(".")
    )
    + r")(?![\w.\-])",
    re.IGNORECASE,
)
# Subcommands of the agent's own command line that change what it is allowed to do or what
# it stores. Read-only uses are caught as well; the model has tools and slash commands for those.
OWN_CLI_SUBCOMMANDS = (
    "auth",
    "config",
    "hooks",
    "plugins",
    "setup",
    "gateway",
    "profile",
    "tools",
    "model",
    "skills",
    "cron",
    "sessions",
    "backup",
    "update",
    "uninstall",
)


def own_command_names() -> set[str]:
    """Names this agent's command line can be started under: the package name, the display
    name in lower case, and every console script the installed distribution declares."""
    names = {APP_NAME, DISPLAY_NAME.lower()}
    try:
        from importlib.metadata import entry_points

        names.update(
            entry.name
            for entry in entry_points(group="console_scripts")
            if entry.value.split(":")[0].startswith(f"{APP_NAME}.")
        )
    except Exception:  # metadata of some other package may be broken
        logger.debug("could not list console scripts", exc_info=True)
    return names


@functools.lru_cache(maxsize=1)
def _own_cli() -> re.Pattern[str]:
    commands = "|".join(re.escape(name) for name in sorted(own_command_names()))
    return re.compile(
        rf"(?:^|[\s;&|(`])(?:{commands}|python[\d.]*\s+-m\s+{re.escape(APP_NAME)})\s+"
        r"(?:(?:-p|--profile)[\s=]+\S+\s+|-\S+\s+)*(?:" + "|".join(OWN_CLI_SUBCOMMANDS) + r")\b"
    )


@functools.lru_cache(maxsize=1)
def _own_names() -> frozenset[str]:
    return frozenset(name.lower() for name in own_command_names())


def reset_own_command_cache() -> None:
    """Forget the agent's own command names, so the next check lists the installed scripts again."""
    _own_cli.cache_clear()
    _own_names.cache_clear()


_PYTHON = re.compile(r"(?:python|pypy)[\d.]*$|py$")
_SUBSTITUTION = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")


def _runs_own_cli(text: str) -> bool:
    """Whether ``text`` starts this agent's own command line with one of the subcommands that
    change what the agent may do: by name, by path, through ``python -m``, through a wrapper
    such as ``sudo``, or through a substitution such as ``$(command -v <name>)``."""
    names = _own_names()

    def named(match: re.Match[str]) -> str:
        inner = (match.group(1) or match.group(2) or "").split()
        # The command is whatever the substitution prints: read it as the name it looks up.
        return (
            f" {APP_NAME} "
            if any(posixpath.basename(word).lower() in names for word in inner)
            else match.group(0)
        )

    for words in simple_commands(_SUBSTITUTION.sub(named, text)):
        arguments = arguments_of(words, names)
        if arguments is None and any(_PYTHON.match(posixpath.basename(word).lower()) for word in words):
            module = next(
                (
                    index
                    for index, word in enumerate(words[:-1])
                    if word == "-m" and words[index + 1].lower().split(".")[0] == APP_NAME
                ),
                None,
            )
            arguments = words[module + 2 :] if module is not None else None
        if arguments is None:
            continue
        index = 0
        while index < len(arguments) and arguments[index].startswith("-"):
            index += 2 if arguments[index] in ("-p", "--profile") else 1
        if index < len(arguments) and arguments[index].lower() in OWN_CLI_SUBCOMMANDS:
            return True
    return False


def _home_spellings() -> list[str]:
    """The ways a command can spell one of this agent's home directories."""
    spellings = {
        f"~/{HOME_DIRNAME}",
        f"$HOME/{HOME_DIRNAME}",
        f"${{HOME}}/{HOME_DIRNAME}",
        f"${HOME_ENV}",
        f"${{{HOME_ENV}}}",
    }
    for home in (get_home(), get_default_root()):
        spellings.update({str(home), str(home.resolve(strict=False))})
    spellings.update(
        {f"%{HOME_ENV}%", f"%LOCALAPPDATA%/{HOME_DIRNAME.lstrip('.')}", f"%USERPROFILE%/{HOME_DIRNAME}"}
    )
    return sorted({spelling.replace("\\", "/") for spelling in spellings})


_HOME_MARK = "\x00agent-home\x00"  # normalize_command drops NUL bytes, so a command cannot contain this
_MARKED_PATH = re.compile(re.escape(_HOME_MARK) + r"""([^\s;&|<>()"'`]*)""")
_PATH_END = r"""(?=[/\s;&|<>()"'`]|$)"""  # the directory itself, not a longer name that starts like it
# The home directory named from the directory above it (`cd ~ && cat <dirname>/...`).
_RELATIVE_HOME = re.compile(r"(?<![\w./~$\-])" + re.escape(HOME_DIRNAME) + _PATH_END, re.IGNORECASE)
_SHELL_DECIDES = re.compile(r"[$`{}]")  # the shell, not the text, decides what such a word names
_GLOB = re.compile(r"[*?\[\]]")
_PARENT_REFERENCE = re.compile(r"(?:^|[\s/=:])\.\.(?:[/\s;&|)]|$)")


def _mark_agent_homes(text: str) -> str:
    """``text`` with every spelling of one of this agent's home directories replaced by a
    mark, the longest spelling first so that a profile's home wins over the root above it."""
    spellings = "|".join(re.escape(spelling) for spelling in sorted(_home_spellings(), key=len, reverse=True))
    marked = re.sub(rf"(?:{spellings}){_PATH_END}", lambda _match: _HOME_MARK, text, flags=re.IGNORECASE)
    return _RELATIVE_HOME.sub(lambda _match: _HOME_MARK, marked)


def _could_name(word: str, name: str) -> bool:
    """Whether the shell could turn ``word`` into ``name``."""
    if _SHELL_DECIDES.search(word):
        return True
    word, name = word.lower(), name.lower()
    return fnmatch.fnmatchcase(name, word) if _GLOB.search(word) else word == name


def _names_protected(parts: list[str]) -> bool:
    """Whether the path ``parts`` inside a home is a protected file, could expand to one, or
    is a directory that holds one. No parts at all is the home itself."""
    candidates = [name.split("/") for name in PROTECTED_PATHS]
    for depth, part in enumerate(parts):
        candidates = [
            candidate
            for candidate in candidates
            if len(candidate) > depth and _could_name(part, candidate[depth])
        ]
        if not candidates:
            return False
    return True


def _reaches_protected(tail: str) -> bool:
    """The same question for ``tail``, the rest of a path after a home directory. A profile
    is a home of its own, so ``profiles/<name>/...`` is read from inside that profile."""
    parts = [part for part in tail.split("/") if part not in ("", ".")]
    if ".." in parts:
        return True
    if (
        parts
        and _could_name(parts[0], get_profiles_root().name)
        and (len(parts) <= 2 or _names_protected(parts[2:]))
    ):
        return True
    return _names_protected(parts)


def _tails_inside_agent_homes(cwd: str) -> list[str]:
    """Where ``cwd`` is inside each agent home that contains it, as a path from that home."""
    if not cwd:
        return []
    try:
        directory = Path(cwd).expanduser().resolve(strict=False)
    except (OSError, RuntimeError):
        return []
    homes = {home.resolve(strict=False) for home in (get_home(), get_default_root())}
    return [directory.relative_to(home).as_posix() for home in homes if directory.is_relative_to(home)]


def _reaches_into_agent_home(text: str, cwd: str) -> bool:
    marked = _mark_agent_homes(text)
    if _HOME_MARK in marked:
        # A protected name next to any mention of the home (`cd <home> && sed -i ... config.yaml`),
        # or a path into the home that is, or could expand to, a protected file.
        return bool(_PROTECTED_NAME.search(text)) or any(
            _reaches_protected(tail) for tail in _MARKED_PATH.findall(marked)
        )
    # Working in the home itself (or in a directory that holds a protected file) every relative
    # name can be one of them. Deeper inside, only a path that climbs back out can.
    tails = _tails_inside_agent_homes(cwd)
    return any(_reaches_protected(tail) for tail in tails) or (
        bool(tails) and _PARENT_REFERENCE.search(text) is not None
    )


def detect_self_access(command: str, cwd: str = "") -> DangerMatch | None:
    """A match when ``command`` reaches for the agent's own settings or credentials: it runs
    the agent's own management command, it names a path into one of the agent's homes that is
    (or could expand to) a protected file or a directory holding one, or it runs from inside
    such a directory."""
    try:
        return _detect_self_access(command, cwd, 0)
    except CommandTooComplexError:
        return SELF_ACCESS


def _detect_self_access(command: str, cwd: str, depth: int) -> DangerMatch | None:
    guard_parse_limits(command, depth)
    # Windows backslashes are separators, not POSIX escapes. Keep both readings.
    plain = shell_plain(command)
    values = variable_values(plain)
    readings = [
        normalize_command(command),
        plain,
        normalize_command(command).replace("\\", "/").translate(QUOTES),
    ]
    for text in readings:
        # A name assembled from a variable on the same line is the name it runs as.
        for expanded in (text, expand_variables(text, values)):
            if (
                _own_cli().search(expanded)
                or _runs_own_cli(expanded)
                or _reaches_into_agent_home(expanded, cwd)
            ):
                return SELF_ACCESS
    for payload in code_payloads(command):
        if _detect_self_access(payload, cwd, depth + 1) is not None:
            return SELF_ACCESS
    return None
