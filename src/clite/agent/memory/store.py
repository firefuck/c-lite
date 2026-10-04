"""Built-in memory: two small files the agent curates itself.

``MEMORY.md`` holds the agent's notes (environment facts, conventions, lessons). ``USER.md``
holds what it knows about the user. Both are bounded in characters: the limit is what forces
the agent to consolidate instead of accumulate.

The snapshot rule: a session's system prompt contains memory as it was when the session
started. Writes during the session go to disk immediately but do not change the prompt,
because a changing system prompt would invalidate the provider's prompt cache on every
write. The next session (or the next compression) picks the new content up.
"""

from __future__ import annotations

import contextlib
import threading
from pathlib import Path
from typing import Any

from clite.core.constants import ensure_dir, get_memories_dir
from clite.core.io import atomic_write_text
from clite.core.threats import describe, scan_text

ENTRY_DELIMITER = "\n§\n"
TARGETS = {"memory": "MEMORY.md", "user": "USER.md"}
_HEADINGS = {
    "memory": "MEMORY (your personal notes)",
    "user": "USER PROFILE (who the user is)",
}

try:
    import fcntl
except ImportError:  # Windows: single-writer by convention; see the roadmap for a portable lock
    fcntl = None  # type: ignore[assignment]

_PROCESS_LOCK = threading.RLock()


class MemoryStore:
    def __init__(self, memory_char_limit: int = 2200, user_char_limit: int = 1375, directory: Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else get_memories_dir()
        self.limits = {"memory": memory_char_limit, "user": user_char_limit}
        self._snapshot: dict[str, list[str]] = {"memory": [], "user": []}
        self.load_from_disk()

    # ── reading ──────────────────────────────────────────────────────────────────────────

    def _path(self, target: str) -> Path:
        return self.directory / TARGETS[target]

    def _read(self, target: str) -> list[str]:
        try:
            text = self._path(target).read_text(encoding="utf-8")
        except OSError:
            return []
        return [entry.strip() for entry in text.split(ENTRY_DELIMITER) if entry.strip()]

    def load_from_disk(self) -> None:
        """Take the snapshot the system prompt will use for the rest of the session."""
        self._snapshot = {target: self._read(target) for target in TARGETS}

    def entries(self, target: str) -> list[str]:
        """Live entries, straight from disk (another session may have written since)."""
        return self._read(target)

    def format_for_system_prompt(self, target: str) -> str:
        """The frozen snapshot as a prompt block; ``""`` when the store is empty."""
        entries = self._snapshot.get(target) or []
        if not entries:
            return ""
        used = len(ENTRY_DELIMITER.join(entries))
        limit = self.limits[target]
        bar = "═" * 46
        header = f"{_HEADINGS[target]} [{round(used * 100 / limit)}% — {used:,}/{limit:,} chars]"
        return f"{bar}\n{header}\n{bar}\n" + ENTRY_DELIMITER.join(entries)

    # ── writing ──────────────────────────────────────────────────────────────────────────

    @contextlib.contextmanager
    def _locked(self):
        ensure_dir(self.directory)
        with _PROCESS_LOCK:
            if fcntl is None:
                yield
                return
            with open(self.directory / ".lock", "a+") as handle:  # noqa: PTH123
                fcntl.flock(handle, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)

    def _result(self, target: str, entries: list[str], message: str) -> dict[str, Any]:
        used, limit = len(ENTRY_DELIMITER.join(entries)), self.limits[target]
        return {"success": True, "target": target, "message": message, "entries": entries,
                "usage": f"{round(used * 100 / limit)}% — {used:,}/{limit:,} chars"}

    def _error(self, target: str, message: str, entries: list[str] | None = None, **extra: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {"success": False, "target": target, "error": message, **extra}
        if entries is not None:
            payload["entries"] = entries
        return payload

    def _write(self, target: str, entries: list[str]) -> None:
        atomic_write_text(self._path(target), ENTRY_DELIMITER.join(entries) + ("\n" if entries else ""))

    @staticmethod
    def _check(content: str) -> str | None:
        threats = scan_text(content)
        return f"Rejected by the security scan ({describe(threats)}). Memory is injected into the system prompt." if threats else None

    def _locate(self, target: str, entries: list[str], old_text: str) -> tuple[int | None, dict[str, Any] | None]:
        needle = (old_text or "").strip()
        if not needle:
            return None, self._error(target, "old_text is required: a short unique substring of the entry.", entries)
        matches = [index for index, entry in enumerate(entries) if needle in entry]
        if not matches:
            return None, self._error(target, f"No entry contains {needle!r}.", entries)
        if len(matches) > 1:
            return None, self._error(target, f"{len(matches)} entries contain {needle!r}. Use a more specific substring.",
                                     matches=[entries[index] for index in matches])
        return matches[0], None

    def add(self, target: str, content: str) -> dict[str, Any]:
        if target not in TARGETS:
            return self._error(target, "target must be 'memory' or 'user'")
        content = (content or "").strip()
        if not content:
            return self._error(target, "content is required")
        rejected = self._check(content)
        if rejected:
            return self._error(target, rejected)
        with self._locked():
            entries = self._read(target)
            if content in entries:
                return self._result(target, entries, "That entry already exists; nothing added.")
            updated = [*entries, content]
            size, limit = len(ENTRY_DELIMITER.join(updated)), self.limits[target]
            if size > limit:
                return self._error(
                    target,
                    f"Adding this would use {size:,} of {limit:,} chars. Replace or remove existing entries "
                    "first: merge related ones and drop what is no longer true.",
                    entries,
                )
            self._write(target, updated)
        return self._result(target, updated, "Entry added.")

    def replace(self, target: str, old_text: str, content: str) -> dict[str, Any]:
        if target not in TARGETS:
            return self._error(target, "target must be 'memory' or 'user'")
        content = (content or "").strip()
        if not content:
            return self._error(target, "content is required; use action='remove' to delete an entry")
        rejected = self._check(content)
        if rejected:
            return self._error(target, rejected)
        with self._locked():
            entries = self._read(target)
            index, error = self._locate(target, entries, old_text)
            if error is not None:
                return error
            assert index is not None  # _locate returns exactly one of the two
            updated = list(entries)
            updated[index] = content
            size, limit = len(ENTRY_DELIMITER.join(updated)), self.limits[target]
            if size > limit:
                return self._error(target, f"The replacement would use {size:,} of {limit:,} chars. Shorten it.", entries)
            self._write(target, updated)
        return self._result(target, updated, "Entry replaced.")

    def remove(self, target: str, old_text: str) -> dict[str, Any]:
        if target not in TARGETS:
            return self._error(target, "target must be 'memory' or 'user'")
        with self._locked():
            entries = self._read(target)
            index, error = self._locate(target, entries, old_text)
            if error is not None:
                return error
            assert index is not None  # _locate returns exactly one of the two
            updated = entries[:index] + entries[index + 1 :]
            self._write(target, updated)
        return self._result(target, updated, "Entry removed.")
