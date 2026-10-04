"""Command approval: the gate between the model and a destructive shell command.

Order of checks, most absolute first:

1. Hardline patterns are refused in every mode. No setting unlocks them.
2. ``approvals.deny`` globs from the user's config are refused in every mode.
3. ``approvals.mode: off`` (or ``--yolo``) lets everything else through.
4. A command matching no dangerous pattern runs.
5. A dangerous command runs if every matched pattern was approved for this session or sits
   on the permanent allowlist.
6. Otherwise the user is asked: once / session / always / deny. With no one to ask (cron, a
   one-shot query) the platform's non-interactive policy decides, and it defaults to deny.
"""

from __future__ import annotations

import fnmatch
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from clite.core.config import atomic_config_update
from clite.plugins.hooks import invoke_hook
from clite.tools.context import ToolContext

logger = logging.getLogger("clite.tools.approval")

# (regex, key, description). The key is what gets remembered when the user approves.
DANGEROUS_PATTERNS: list[tuple[str, str, str]] = [
    (r"\brm\s+(-[a-zA-Z]*[rRf][a-zA-Z]*\s+)+", "rm_recursive_or_force", "recursive or forced delete"),
    (r"\brm\s+--(recursive|force)\b", "rm_recursive_or_force", "recursive or forced delete"),
    (r"\bfind\b.*\s-delete\b", "find_delete", "find with -delete"),
    (r"\bfind\b.*-exec\s+rm\b", "find_delete", "find executing rm"),
    (r"\bchmod\s+(-[a-zA-Z]+\s+)*(777|666|a\+w|o\+w)\b", "chmod_world_writable", "world-writable permissions"),
    (r"\bchown\s+(-[a-zA-Z]+\s+)*-R\b|\bchown\s+-[a-zA-Z]*R", "chown_recursive", "recursive ownership change"),
    (r"\bmkfs(\.\w+)?\b", "mkfs", "format a filesystem"),
    (r"\bdd\b.*\bof=", "dd_write", "dd writing to a target"),
    (r">\s*/dev/(sd|nvme|hd|vd|disk)", "write_block_device", "write to a block device"),
    (r">\s*/etc/", "write_etc", "overwrite a system config file"),
    (r"\b(sudo|doas)\b", "privilege_escalation", "run with elevated privileges"),
    (r"\b(shutdown|reboot|halt|poweroff)\b", "power_control", "shut down or reboot the machine"),
    (r"\b(systemctl|service)\s+(stop|disable|mask|restart)\b", "service_control", "stop or disable a service"),
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
    (r"\b(docker|podman)\s+(system\s+prune|volume\s+(rm|prune)|rm\s+-f)", "container_destroy", "destroy containers or volumes"),
    (r"\bkubectl\s+delete\b", "kubectl_delete", "delete cluster resources"),
    (r"\bterraform\s+(destroy|apply\b.*-auto-approve)", "terraform_destroy", "destroy or auto-apply infrastructure"),
    (r"\bcrontab\s+-r\b", "crontab_remove", "remove the crontab"),
    (r"(^|[;&|]\s*)(python3?|node|perl|ruby)\s+-[ce]\s+.*(rmtree|unlink|rm\s+-)", "script_delete", "script that deletes files"),
    (r"\b(mv|cp)\b.*\s(~/)?\.(ssh|aws|gnupg)/", "credential_dir_write", "write into a credential directory"),
    (r">\s*~?/?\S*\.(bashrc|zshrc|profile|bash_profile)\b", "shell_rc_overwrite", "overwrite a shell startup file"),
]

# Refused in every mode: there is no legitimate reason for an agent to run these.
HARDLINE_PATTERNS: list[tuple[str, str]] = [
    (r"\brm\s+(-[a-zA-Z]+\s+)*-[a-zA-Z]*[rR][a-zA-Z]*\s+(-[a-zA-Z]+\s+)*(--no-preserve-root\s+)?/(\s|$|\*)", "delete the root filesystem"),
    (r"\brm\s+.*--no-preserve-root", "delete the root filesystem"),
    (r"\brm\s+(-[a-zA-Z]+\s+)*-[a-zA-Z]*[rR][a-zA-Z]*\s+(-[a-zA-Z]+\s+)*(~|\$HOME)/?(\s|$)", "delete the home directory"),
    (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "fork bomb"),
    (r"\bmkfs(\.\w+)?\s+(-\S+\s+)*/dev/(sd|nvme|hd|vd)", "format a disk"),
    (r"\bdd\b.*\bof=/dev/(sd|nvme|hd|vd|disk)", "overwrite a disk"),
    (r">\s*/dev/(sd|nvme|hd|vd)[a-z0-9]*", "overwrite a disk"),
]

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_COMPILED_DANGEROUS = [(re.compile(p, re.IGNORECASE | re.DOTALL), key, desc) for p, key, desc in DANGEROUS_PATTERNS]
_COMPILED_HARDLINE = [(re.compile(p, re.IGNORECASE | re.DOTALL), desc) for p, desc in HARDLINE_PATTERNS]

CHOICES = ("once", "session", "always", "deny")


@dataclass(frozen=True)
class DangerMatch:
    key: str
    description: str


@dataclass
class ApprovalDecision:
    approved: bool
    reason: str = ""
    choice: str = "auto"  # auto | once | session | always | deny | hardline | denylist | policy
    matches: list[DangerMatch] = field(default_factory=list)


_SESSION_APPROVED: dict[str, set[str]] = {}
_LOCK = threading.Lock()


def reset_approval_state() -> None:
    with _LOCK:
        _SESSION_APPROVED.clear()


def normalize_command(command: str) -> str:
    """Undo the cheap obfuscations: ANSI escapes, NUL bytes, full-width look-alikes."""
    text = _ANSI.sub("", command).replace("\x00", "")
    return unicodedata.normalize("NFKC", text)


def detect_dangerous_command(command: str) -> list[DangerMatch]:
    text = normalize_command(command)
    found: dict[str, DangerMatch] = {}
    for pattern, key, description in _COMPILED_DANGEROUS:
        if key not in found and pattern.search(text):
            found[key] = DangerMatch(key, description)
    return list(found.values())


def detect_hardline(command: str) -> str | None:
    text = normalize_command(command)
    for pattern, description in _COMPILED_HARDLINE:
        if pattern.search(text):
            return description
    return None


def _non_interactive_policy(ctx: ToolContext) -> str:
    if ctx.platform == "cron":
        return str(ctx.setting("approvals.cron_mode", "deny"))
    return str(ctx.setting("approvals.single_query_mode", "deny"))


def check_command(command: str, ctx: ToolContext | None = None) -> ApprovalDecision:
    """Decide whether ``command`` may run. May block on the user's answer."""
    ctx = ctx or ToolContext()
    hardline = detect_hardline(command)
    if hardline:
        return ApprovalDecision(False, f"Refused: this command would {hardline}. No setting allows it.", "hardline")

    normalized = normalize_command(command)
    for glob in ctx.setting("approvals.deny", []) or []:
        if fnmatch.fnmatch(normalized, str(glob)):
            return ApprovalDecision(False, f"Refused by the approvals.deny rule {glob!r}.", "denylist")

    mode = ctx.approval_mode or str(ctx.setting("approvals.mode", "manual"))
    if mode == "off":
        return ApprovalDecision(True, "approvals are off", "auto")

    matches = detect_dangerous_command(command)
    if not matches:
        return ApprovalDecision(True, "no dangerous pattern", "auto")

    keys = {match.key for match in matches}
    session_key = ctx.session_id or "default"
    allowlist = set(ctx.setting("command_allowlist", []) or [])
    with _LOCK:
        approved = set(_SESSION_APPROVED.get(session_key, ()))
    if keys <= (allowlist | approved):
        return ApprovalDecision(True, "previously approved", "auto", matches)

    description = "; ".join(match.description for match in matches)
    approve = getattr(ctx.callbacks, "approve", None)
    if approve is None:
        if _non_interactive_policy(ctx) == "approve":
            return ApprovalDecision(True, "non-interactive policy: approve", "policy", matches)
        return ApprovalDecision(
            False,
            f"Refused: this command needs approval ({description}) and there is no one to ask. "
            "Use a safer command, or tell the user what needs to be run.",
            "policy",
            matches,
        )

    invoke_hook("pre_approval_request", command=command, description=description,
                pattern_keys=sorted(keys), session_key=session_key, surface=ctx.platform)
    try:
        choice = str(approve(command=command, description=description, pattern_keys=sorted(keys)) or "deny")
    except Exception:  # noqa: BLE001 - a broken prompt must fail closed
        logger.warning("approval callback failed", exc_info=True)
        choice = "deny"
    if choice not in CHOICES:
        choice = "deny"
    invoke_hook("post_approval_response", command=command, description=description,
                pattern_keys=sorted(keys), session_key=session_key, surface=ctx.platform, choice=choice)

    if choice == "deny":
        return ApprovalDecision(False, "The user denied this command. Do not retry it; ask what they prefer.", "deny", matches)
    if choice in ("session", "always"):
        with _LOCK:
            _SESSION_APPROVED.setdefault(session_key, set()).update(keys)
    if choice == "always":
        _remember_always(keys)
    return ApprovalDecision(True, f"approved ({choice})", choice, matches)


def _remember_always(keys: set[str]) -> None:
    def mutate(document: dict[str, Any]) -> None:
        current = list(document.get("command_allowlist") or [])
        document["command_allowlist"] = sorted(set(current) | keys)

    try:
        atomic_config_update(mutate)
    except Exception:  # noqa: BLE001 - the approval still holds for this session
        logger.warning("could not persist command_allowlist", exc_info=True)
