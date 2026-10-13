"""Dangerous and forbidden commands: the pattern catalogues and the detectors that read them.

``DANGEROUS_PATTERNS`` need approval, and a yes can be remembered for the session or forever
under the pattern's key. ``HARDLINE_PATTERNS`` are refused in every mode, and so is a recursive
``rm`` whose target resolves to the root, the home directory (or a directory that holds it), or
one of ``SYSTEM_DIRECTORIES``. Both catalogues are matched only at command positions, in both
readings of the command and in every code payload inside it (see ``shell_reading``).
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from pathlib import Path

from clite.tools.shell_reading import (
    QUOTES,
    CommandTooComplexError,
    arguments_of,
    code_payloads,
    contained,
    expand_variables,
    guard_parse_limits,
    position_readings,
    simple_commands,
)

# (regex, key, description). The key is what gets remembered when the user approves.
DANGEROUS_PATTERNS: list[tuple[str, str, str]] = [
    (r"\b(?:rd|rmdir)\s+/s\b|\b(?:del|erase)\s+", "windows_delete", "delete files or directories"),
    (r"\brm\s+(-[a-zA-Z]*[rRf][a-zA-Z]*\s+)+", "rm_recursive_or_force", "recursive or forced delete"),
    (r"\brm\s+--(recursive|force)\b", "rm_recursive_or_force", "recursive or forced delete"),
    (r"\bfind\b.*\s-delete\b", "find_delete", "find with -delete"),
    (r"\bfind\b.*-exec\s+rm\b", "find_delete", "find executing rm"),
    (
        r"\bchmod\s+(-[a-zA-Z]+\s+)*(777|666|a\+w|o\+w)\b",
        "chmod_world_writable",
        "world-writable permissions",
    ),
    (
        r"\bchown\s+(-[a-zA-Z]+\s+)*-R\b|\bchown\s+-[a-zA-Z]*R",
        "chown_recursive",
        "recursive ownership change",
    ),
    (r"\bmkfs(\.\w+)?\b", "mkfs", "format a filesystem"),
    (r"\bdd\b.*\bof=", "dd_write", "dd writing to a target"),
    (r">\s*/dev/(sd|nvme|hd|vd|disk)", "write_block_device", "write to a block device"),
    (r">\s*/etc/", "write_etc", "overwrite a system config file"),
    (r"\b(sudo|doas)\b", "privilege_escalation", "run with elevated privileges"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "power_control", "shut down or reboot the machine"),
    (
        r"\b(systemctl|service)\s+(stop|disable|mask|restart)\b",
        "service_control",
        "stop or disable a service",
    ),
    (r"\bkill(all)?\s+(-9|-KILL|-SIGKILL)\b|\bpkill\s+-9\b", "force_kill", "force-kill processes"),
    (r"\b(curl|wget)\b[^|;&]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", "pipe_to_shell", "pipe a download into a shell"),
    (r"\b(ba|z)?sh\s+-c\s+[\"']?\$\((curl|wget)", "pipe_to_shell", "execute downloaded code"),
    (r"\bgit\s+push\b.*(--force\b|-f\b|--force-with-lease\b)", "git_force_push", "force push"),
    (r"\bgit\s+reset\s+--hard\b", "git_reset_hard", "discard uncommitted work"),
    (r"\bgit\s+clean\s+-[a-zA-Z]*[fd]", "git_clean", "delete untracked files"),
    (r"\bgit\s+(checkout|restore)\s+(--\s+)?\.(\s|$)", "git_discard_all", "discard all local changes"),
    (r"\bdrop\s+(table|database|schema)\b", "sql_drop", "SQL DROP"),
    (r"\bdelete\s+from\s+\w+\s*(;|$|\")", "sql_delete_all", "SQL DELETE without WHERE"),
    (r"\btruncate\s+table\b", "sql_truncate", "SQL TRUNCATE"),
    (
        r"\b(docker|podman)\s+(system\s+prune|volume\s+(rm|prune)|rm\s+-f)",
        "container_destroy",
        "destroy containers or volumes",
    ),
    (r"\bkubectl\s+delete\b", "kubectl_delete", "delete cluster resources"),
    (
        r"\bterraform\s+(destroy|apply\b.*-auto-approve)",
        "terraform_destroy",
        "destroy or auto-apply infrastructure",
    ),
    (r"\bcrontab\s+-r\b", "crontab_remove", "remove the crontab"),
    # Deletes spelled directly in code, which is what `execute_code` runs: a call that removes
    # a tree or a file is the destructive command it wraps, whatever syntax spells it. This is
    # why the code-execution tool sends its text through this gate. The same call inside
    # ``python -c``/``node -e``/``perl -e``/``ruby -e`` is caught when that payload is re-read.
    (
        r"\brmtree\s*\(|\bos\.(remove|unlink|rmdir|removedirs)\s*\(|\bshutil\.rmtree\s*\(",
        "script_delete",
        "script that deletes files",
    ),
    (
        r"\b(unlinkSync|rmSync|rmdirSync|deleteSync)\s*\(|\bFile\.(delete|unlink)\s*\(|\bunlink\s*[\"']",
        "script_delete",
        "script that deletes files",
    ),
    (r"\b(os|shutil)\.(unlink|rmdir|remove|rmtree)\s*\(", "script_delete", "script that deletes files"),
    (
        r"\bsubprocess\.\w+\s*\(\s*[\[\(]?\s*[\"']rm[\"']\s*,\s*[\"']-",
        "script_delete",
        "script that deletes files",
    ),
    (r"\b(mv|cp)\b.*\s(~/)?\.(ssh|aws|gnupg)/", "credential_dir_write", "write into a credential directory"),
    (
        r">\s*~?/?\S*\.(bashrc|zshrc|profile|bash_profile)\b",
        "shell_rc_overwrite",
        "overwrite a shell startup file",
    ),
]

# Refused in every mode: there is no legitimate reason for an agent to run these.
HARDLINE_PATTERNS: list[tuple[str, str]] = [
    (
        r"\brm\s+(-[a-zA-Z]+\s+)*-[a-zA-Z]*[rR][a-zA-Z]*\s+(-[a-zA-Z]+\s+)*(--no-preserve-root\s+)?/(\s|$|\*)",
        "delete the root filesystem",
    ),
    (r"\brm\s+.*--no-preserve-root", "delete the root filesystem"),
    (
        r"\brm\s+(-[a-zA-Z]+\s+)*-[a-zA-Z]*[rR][a-zA-Z]*\s+(-[a-zA-Z]+\s+)*(~|\$HOME)/?(\s|$)",
        "delete the home directory",
    ),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    (r"\bmkfs(\.\w+)?\s+(-\S+\s+)*/dev/(sd|nvme|hd|vd)", "format a disk"),
    (r"\bdd\b.*\bof=/dev/(sd|nvme|hd|vd|disk)", "overwrite a disk"),
    (r">\s*/dev/(sd|nvme|hd|vd)[a-z0-9]*", "overwrite a disk"),
    # Absolute prohibitions carried over from Hermes: a signal the machine cannot refuse to
    # obey, or a power state no agent should change. Only at a command position, so a message
    # that merely *mentions* them stays data.
    (
        r"(?:^|[;&|()`]\s*|\b(?:sudo|doas|env|exec|nohup|setsid|nice|timeout|stdbuf)\b\s+\S*\s*)kill\s+(-[a-zA-Z]*1\b|-[a-zA-Z]*HUP\b|-[a-zA-Z]*SIGHUP\b)",
        "send a hangup signal to a process",
    ),
    (
        r"(?:^|[;&|()`]\s*|\b(?:sudo|doas|env|exec|nohup|setsid|nice|timeout|stdbuf)\b\s+\S*\s*)(shutdown|reboot|halt|poweroff)\b",
        "shut down, reboot, or change the machine's run level",
    ),
    (
        r"(?:^|[;&|()`]\s*|\b(?:sudo|doas|env|exec|nohup|setsid|nice|timeout|stdbuf)\b\s+\S*\s*)init\s+[06]\b",
        "shut down, reboot, or change the machine's run level",
    ),
    (r"(?:^|[;&|()`]\s*)(?:sudo\s+)?(\w*/)?mkfs(\.\w+)?\b", "format a disk"),
]

_COMPILED_DANGEROUS = [
    (re.compile(p, re.IGNORECASE | re.DOTALL), key, desc) for p, key, desc in DANGEROUS_PATTERNS
]
_COMPILED_HARDLINE = [(re.compile(p, re.IGNORECASE | re.DOTALL), desc) for p, desc in HARDLINE_PATTERNS]


@dataclass(frozen=True)
class DangerMatch:
    key: str
    description: str


# ── deletes with no way back ─────────────────────────────────────────────────────────────

# Besides the root and the home directory (and whatever holds the home directory).
SYSTEM_DIRECTORIES = frozenset(
    {
        "/home",
        "/root",
        "/etc",
        "/usr",
        "/var",
        "/bin",
        "/sbin",
        "/boot",
        "/lib",
        "/lib64",
        "/Users",
        "/System",
        "/Library",
    }
)
_RM = frozenset({"rm"})
_TRAILING_GLOB = re.compile(r"(?:^|(?<=/))\.?\*+$")  # `dir/*` and `dir/.*` empty `dir`
_HOME_WORD = re.compile(r"^(?:~|\$HOME)(?=/|$)")
_PWD_WORD = re.compile(r"^\$PWD(?=/|$)")


def _path_text(path: str) -> str:
    path = path.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", path):
        path = "/" + path.lower()
    return posixpath.normpath(path)


def _user_home() -> str | None:
    try:
        return _path_text(str(Path.home()))
    except RuntimeError:  # no HOME and no passwd entry: nothing to compare against
        return None


def _absolute(word: str, where: str | None) -> str | None:
    """``word`` as a normalised absolute path, read from the directory ``where``; ``None``
    when only a running shell could tell."""
    word = word.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", word):
        word = "/" + word.lower()
    home = _user_home()
    if home:
        word = _HOME_WORD.sub(lambda _match: home, word)
    if where:
        word = _PWD_WORD.sub(lambda _match: where, word)
    if "$" in word or "`" in word or word.startswith("~"):
        return None
    if not word.startswith("/"):
        if not where:
            return None
        word = posixpath.join(where, word)
    return posixpath.normpath("/" + word.lstrip("/"))


def _victim(path: str) -> str | None:
    home = _user_home()
    if path == "/":
        return "delete the root filesystem"
    if home and path == home:
        return "delete the home directory"
    if home and home.startswith(path + "/"):
        return "delete the directory that holds the home directory"
    if path in SYSTEM_DIRECTORIES:
        return "delete a system directory"
    return None


def _recursive_delete_victim(text: str, cwd: str = "") -> str | None:
    """What a recursive ``rm`` in ``text`` would destroy beyond recovery, if anything: the
    root, the home directory, or a system directory. Targets are read the way the shell
    resolves them (``~``, ``$HOME``, ``..``, a trailing ``/*``), from ``cwd`` when it is
    known, following any ``cd`` earlier on the same command line."""
    where: str | None = _path_text(cwd) if cwd else None
    for words in simple_commands(text, break_on_parens=False):
        if words[0] in ("cd", "pushd"):
            target = words[1] if len(words) > 1 else "~"
            where = None if target.startswith("-") else _absolute(target, where)
            continue
        arguments = arguments_of(words, _RM)
        if arguments is None:
            continue
        options_end = arguments.index("--") if "--" in arguments else len(arguments)
        flags = [word for word in arguments[:options_end] if word.startswith("-")]
        targets = [word for word in arguments[:options_end] if not word.startswith("-")] + arguments[
            options_end + 1 :
        ]
        if "--no-preserve-root" in flags:
            return "delete the root filesystem"
        if not any(
            flag == "--recursive" or (not flag.startswith("--") and "r" in flag.lower()) for flag in flags
        ):
            continue
        for target in targets:
            path = _absolute(_TRAILING_GLOB.sub("", target) or ".", where)
            victim = _victim(path) if path else None
            if victim:
                return victim
    return None


# ── the detectors ────────────────────────────────────────────────────────────────────────


class _Collected:
    """The patterns found so far, keyed so a later, richer description does not overwrite one."""

    def __init__(self) -> None:
        self.matches: dict[str, DangerMatch] = {}

    def add(self, key: str, description: str) -> None:
        self.matches.setdefault(key, DangerMatch(key, description))


def detect_dangerous_command(command: str) -> list[DangerMatch]:
    """The soft patterns ``command`` matches, read at its command positions.

    A quoted run that is only data (``git commit -m "rm -rf /"``) is a mention, not a command,
    so a match wholly inside it is skipped. A run that carries code (``bash -c "..."``,
    ``python -c "..."``) is read as a command in its own right."""
    try:
        return list(_detect_dangerous(command, 0).matches.values())
    except CommandTooComplexError:
        # The size and depth limits are enforced by ``check_command``; here a command too big
        # to read is treated as matching every pattern, which is the safe side for a caller
        # that only asks "is this dangerous".
        return [DangerMatch("parse_limit", "command too large or too deeply nested to inspect")]


def _detect_dangerous(command: str, depth: int) -> _Collected:
    guard_parse_limits(command, depth)
    collected = _Collected()
    for text, data_spans, values in position_readings(command):
        text = expand_variables(text, values)
        for pattern, key, description in _COMPILED_DANGEROUS:
            if key in collected.matches:
                continue
            for hit in pattern.finditer(text):
                if not contained(hit.span(), text, data_spans):
                    collected.add(key, description)
                    break
    for payload in code_payloads(command):
        for found in _detect_dangerous(payload, depth + 1).matches.values():
            collected.matches.setdefault(found.key, found)
    return collected


def detect_hardline(command: str, cwd: str = "") -> str | None:
    """Why ``command`` is refused in every mode, or ``None``. ``cwd`` is the directory it would
    run in, when known: a relative ``rm -rf *`` is only catastrophic in some places."""
    try:
        return _detect_hardline(command, cwd, 0)
    except CommandTooComplexError as exc:
        return str(exc.reason)


def _detect_hardline(command: str, cwd: str, depth: int) -> str | None:
    guard_parse_limits(command, depth)
    for text, data_spans, values in position_readings(command):
        text = expand_variables(text, values)
        for pattern, description in _COMPILED_HARDLINE:
            for match in pattern.finditer(text):
                if not contained(match.span(), text, data_spans):
                    return description
        # Read the target both ways: as the shell resolves escapes, and with Windows
        # separators, where a backslash is a path separator and not an escape. Quotes go, so
        # a quoted target (``rm -rf "C:\\Users\\me"``) is read as the path it names.
        for candidate in (text, text.replace("\\", "/").translate(QUOTES)):
            victim = _recursive_delete_victim(candidate, cwd)
            if victim:
                return victim
    for payload in code_payloads(command):
        reason = _detect_hardline(payload, cwd, depth + 1)
        if reason:
            return reason
    return None
