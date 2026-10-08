"""Deeper scan for a skill that came from outside.

``core.threats.scan_text`` finds the injection patterns in one piece of text. A skill is more
than its ``SKILL.md``: it can carry scripts, and a script runs with the user's own rights once
the agent calls it. This module reads the whole bundle and reports what would be written before
anything is written — every text file, not just ``SKILL.md``, the commands each script
contains, and the hosts the bundle talks to.

The report is for a person to read, so it names files. A finding is a refusal, not a rewrite:
the skill is installed only if the user looks at the report and says yes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from clite.core.threats import describe, scan_text

# Files under a directory named ``scripts`` are reported command by command, in addition to the
# plain injection scan every text file gets.
_SCRIPT_DIR = "scripts"
# (pattern, command). The names are what a person recognises, not every spelling of the call.
_COMMANDS: list[tuple[str, str]] = [
    (r"subprocess\.(?:run|call|check_call|check_output|Popen)\s*\(", "subprocess"),
    (r"os\.system\s*\(", "os.system"),
    (r"os\.popen\s*\(", "os.popen"),
    (r"\bshell\s*=\s*True\b", "shell=True"),
    (r"\bsh\s+-c\b", "sh -c"),
    (r"\bbash\s+-c\b", "bash -c"),
    (r"\beval\s*\(", "eval"),
    (r"\bexec\s*\(", "exec"),
    (r"\b(?:curl|wget)\b", "download"),
    (r"\b(?:nc|netcat|ncat)\b", "netcat"),
    (r"\brm\s+-rf\b", "rm -rf"),
    (r"\bchmod\s+\+x\b", "chmod +x"),
    (r"\b(?:pip|pip3)\s+install\b", "pip install"),
    (r"\bnpm\s+(?:install|i)\b", "npm install"),
]
_COMPILED = [(re.compile(pattern), name) for pattern, name in _COMMANDS]
_URL = re.compile(r"\b(?:https?|ftp|ssh)://([A-Za-z0-9.\-]+)")
# ``curl evil.test`` with no scheme is common enough to be worth naming.
_BARE_HOST = re.compile(r"\b(?:curl|wget|nc|ncat|ssh|scp)\s+(?:-\S+\s+)*([A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b")
_SCRIPT_SUFFIXES = {".py", ".sh", ".bash", ".zsh", ".js", ".mjs", ".cjs", ".rb", ".pl", ".ps1"}
# A NUL byte in the first block is the classic sign of a binary file.
_BINARY_SNIFF = 8192


@dataclass
class ScanReport:
    """What a bundle from outside contains, ready to be shown to a person."""

    threats: dict[str, str] = field(default_factory=dict)
    scripts: dict[str, tuple[str, ...]] = field(default_factory=dict)
    hosts: tuple[str, ...] = ()
    binaries: tuple[str, ...] = ()
    text_files: int = 0

    @property
    def blocked(self) -> bool:
        """True when the bundle may not be installed on the user's own say-so alone."""
        return bool(self.threats or self.binaries)

    @property
    def review(self) -> bool:
        """True when there is nothing to refuse but something worth reading first."""
        return bool(self.scripts or self.hosts)

    @property
    def clean(self) -> bool:
        return not self.blocked and not self.review

    def lines(self) -> list[str]:
        """The report as plain lines, one finding per line, for a terminal or a test."""
        out: list[str] = []
        for path, what in sorted(self.threats.items()):
            out.append(f"refused  {path}: {what}")
        for path in sorted(self.binaries):
            out.append(f"refused  {path}: not a text file")
        for path, commands in sorted(self.scripts.items()):
            out.append(f"script   {path}: {', '.join(commands)}")
        if self.hosts:
            out.append(f"hosts    {', '.join(self.hosts)}")
        return out

    def summary(self) -> str:
        """One line for a caller that has no room for the whole report."""
        if self.blocked:
            return f"{len(self.threats)} flagged file(s), {len(self.binaries)} binary file(s)"
        if self.review:
            return f"{len(self.scripts)} script(s), {len(self.hosts)} host(s)"
        return "nothing to report"


def looks_binary(content: bytes) -> bool:
    """True when the bytes are not text. A NUL byte in the head is the usual giveaway."""
    return b"\x00" in content[:_BINARY_SNIFF]


def extract_commands(text: str) -> tuple[str, ...]:
    """The command names a script contains, in the order they first appear."""
    found: dict[str, None] = {}
    for pattern, name in _COMPILED:
        if name not in found and pattern.search(text):
            found[name] = None
    return tuple(found)


def scan_bundle(files: dict[str, bytes]) -> ScanReport:
    """Read every file in a bundle and report what it holds."""
    report = ScanReport()
    hosts: set[str] = set()
    for path, content in sorted(files.items()):
        if looks_binary(content):
            report.binaries = (*report.binaries, path)
            continue
        text = content.decode("utf-8", errors="replace")
        report.text_files += 1
        threats = scan_text(text)
        if threats:
            report.threats[path] = describe(threats)
        hosts.update(_URL.findall(text))
        hosts.update(_BARE_HOST.findall(text))
        parts = PurePosixPath(path).parts
        if _SCRIPT_DIR in parts[:-1] or PurePosixPath(path).suffix.lower() in _SCRIPT_SUFFIXES:
            commands = extract_commands(text)
            if commands:
                report.scripts[path] = commands
    report.hosts = tuple(sorted(hosts))
    return report
