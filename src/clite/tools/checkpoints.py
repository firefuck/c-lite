"""Per-session file checkpoints, so the agent's own edits can be rolled back.

Before ``write_file`` or ``patch`` changes a file, the file's previous state is saved under
``<home>/checkpoints/<session id>/turn-<n>/``. One directory per turn holds every file the
agent touched in that turn, so ``/rollback`` can undo the last turn (or the last *n* turns)
without reasoning about the individual edits.

Only files that the agent changed through the file tools are recorded. A ``terminal`` command
writes through the shell and never passes through here, so its changes are invisible to
``/rollback``: this is the documented boundary of the feature, not an oversight.

Two guards hold:

* A file the read tools refuse (``read_denied_reason``) is never copied into the store. The
  store is plain text on disk, so saving a credential file there would move a secret the agent
  is not allowed to read into a place it, and the model, can read.
* Nothing here raises at the call site: a checkpoint that cannot be written is reported to the
  model as a warning attached to a still-successful write, never as a failed edit.

The store is capped by total size and pruned following ``sessions.retention_days``, the same
knob the session database uses, from :func:`prune_checkpoints`.
"""

from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from clite.core.config import get_path
from clite.core.constants import get_checkpoints_dir
from clite.core.io import atomic_write_text
from clite.tools.file_safety import read_denied_reason

logger = logging.getLogger("clite.tools.checkpoints")

MANIFEST_NAME = "manifest.json"
FILES_DIRNAME = "files"
# Each turn's directory is ``turn-00007``: zero-padded so a plain sort is turn order.
TURN_PREFIX = "turn-"
TURN_DIGITS = 5
# A single saved file larger than this is not copied: the checkpoint must not double the disk
# cost of editing one huge file. The rollback for that file then reports it as skipped.
MAX_FILE_BYTES = 5_000_000

# In-process memory of the turn number handed out per conversation, so a tool call decides the
# turn without touching the disk on every change. Keyed by ``(id(agent), session_id)``.
_LAST_TURN: dict[tuple[int, str], tuple[int, int]] = {}
_TURN_LOCK = threading.Lock()


def reset_turn_tracking() -> None:
    """Forget the per-conversation turn numbers (called between tests)."""
    with _TURN_LOCK:
        _LAST_TURN.clear()


@dataclass
class Change:
    """One file's previous state inside a turn group.

    ``kind`` is what the agent did to the file: ``modified`` (content changed), ``created``
    (did not exist before, so rollback removes it) or ``deleted`` (removed, so rollback brings
    it back). ``saved`` is the file name inside the group's ``files/`` directory holding the
    old bytes, or ``None`` when there was nothing to save (a creation) or the file was too
    large to copy.
    """

    path: str
    kind: str
    saved: str | None = None
    size: int = 0
    skipped_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"path": self.path, "kind": self.kind}
        if self.saved is not None:
            payload["saved"] = self.saved
        if self.size:
            payload["size"] = self.size
        if self.skipped_reason:
            payload["skipped_reason"] = self.skipped_reason
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Change:
        return cls(
            path=str(data.get("path", "")),
            kind=str(data.get("kind", "modified")),
            saved=data.get("saved"),
            size=int(data.get("size") or 0),
            skipped_reason=data.get("skipped_reason"),
        )


@dataclass
class TurnGroup:
    """Every change the agent made in one turn."""

    turn: int
    created_at: float = field(default_factory=time.time)
    changes: list[Change] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "turn": self.turn,
            "created_at": self.created_at,
            "changes": [change.to_dict() for change in self.changes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TurnGroup:
        return cls(
            turn=int(data.get("turn") or 0),
            created_at=float(data.get("created_at") or 0),
            changes=[Change.from_dict(item) for item in data.get("changes") or []],
        )


@dataclass
class RollbackResult:
    """What a rollback did, for the surface to report."""

    turns: int = 0
    restored: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    restored_groups: list[int] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.restored_groups

    def summary(self) -> str:
        if self.empty:
            return "No checkpoints to roll back."
        parts = [
            f"Rolled back {len(self.restored_groups)} turn(s): "
            f"{len(self.restored)} file(s) restored, {len(self.removed)} file(s) removed."
        ]
        for path, reason in self.skipped:
            parts.append(f"  skipped {path} ({reason})")
        return "\n".join(parts)


# ── layout ───────────────────────────────────────────────────────────────────────────────


def session_dir(session_id: str) -> Path:
    """Directory holding every checkpoint of ``session_id``.

    The id goes through :func:`_safe_name` so a crafted session id can never escape the store.
    """
    return get_checkpoints_dir() / _safe_name(session_id)


def _safe_name(name: str) -> str:
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in name.strip())
    return safe or "session"


def _turn_dir(session_id: str, turn: int) -> Path:
    return session_dir(session_id) / f"{TURN_PREFIX}{turn:0{TURN_DIGITS}d}"


def _read_manifest(directory: Path) -> TurnGroup | None:
    manifest = directory / MANIFEST_NAME
    try:
        return TurnGroup.from_dict(json.loads(manifest.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None


def _write_manifest(directory: Path, group: TurnGroup) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_text(directory / MANIFEST_NAME, json.dumps(group.to_dict(), ensure_ascii=False, indent=2))


def _groups(session_id: str) -> list[TurnGroup]:
    """Every stored turn group of ``session_id``, oldest first."""
    root = session_dir(session_id)
    if not root.is_dir():
        return []
    groups = []
    for entry in sorted(root.iterdir(), key=lambda path: path.name):
        if not entry.is_dir() or not entry.name.startswith(TURN_PREFIX):
            continue
        group = _read_manifest(entry)
        if group is not None and group.changes:
            groups.append(group)
    return groups


# ── recording ────────────────────────────────────────────────────────────────────────────


def turn_id_for(ctx: Any) -> int:
    """The current turn's number for a tool call, for grouping a turn's changes together.

    The turn's user message is appended before any tool runs, so counting the user messages the
    agent holds gives a number that is stable for the whole turn and grows by one per turn.
    Compression and undo can make that count drop later, so a small in-process map remembers the
    last count seen per conversation and only starts a new turn when the count changes; a re-used
    (lower) count therefore never splits or merges two turns. When the count is first seen, the
    number is floored above every stored group of the session, so a resumed session never
    overwrites an older group. When there is no agent (a direct call in a test or a script) every
    change lands in turn 1.
    """
    count = _user_message_count(ctx)
    key = (id(_process_key(ctx)), _session_of(ctx))
    with _TURN_LOCK:
        seen = _LAST_TURN.get(key)
        if seen is not None:
            last_count, last_turn = seen
            turn = last_turn if count == last_count else max(last_turn + 1, count)
        else:
            turn = max(count, 1, _highest_stored_turn(_session_of(ctx)))
        _LAST_TURN[key] = (count, turn)
    return turn


def _highest_stored_turn(session_id: str) -> int:
    groups = _groups(session_id)
    return groups[-1].turn if groups else 0


def _user_message_count(ctx: Any) -> int:
    agent = getattr(ctx, "agent", None)
    messages = getattr(agent, "messages", None) if agent is not None else None
    if not messages:
        return 0
    count = 0
    for message in messages:
        if (
            message.get("role") != "user"
            or message.get("display_kind") == "internal"
            or message.get("is_summary")
        ):
            continue
        count += 1
    return count


def _session_of(ctx: Any) -> str:
    return str(getattr(ctx, "session_id", "") or "")


def _process_key(ctx: Any) -> Any:
    """A stable in-process identity for the conversation the call belongs to."""
    agent = getattr(ctx, "agent", None)
    return agent if agent is not None else _session_of(ctx)


def record_change(
    session_id: str,
    path: str,
    *,
    before: str | None,
    existed: bool,
    turn: int,
    deleted: bool = False,
) -> Change | None:
    """Save the previous state of ``path`` and return the recorded change.

    Returns ``None`` when nothing is recorded: a file the read tools refuse is never copied,
    and a ``created`` file that already has an entry this turn is not stored twice.
    """
    if not session_id or not path:
        return None
    denied = read_denied_reason(path)
    if denied:
        # Never let the store hold what the model is not allowed to read.
        return None

    directory = _turn_dir(session_id, turn)
    group = _read_manifest(directory) or TurnGroup(turn=turn)
    # The first change to a file in a turn decides what rollback must do to it. A later change
    # to the same file in the same turn keeps the original entry: rollback restores the state
    # from before the turn began, not before the last edit.
    if any(change.path == path for change in group.changes):
        return next(change for change in group.changes if change.path == path)

    if not existed:
        kind = "created"
    elif deleted:
        kind = "deleted"
    else:
        kind = "modified"

    change = Change(path=path, kind=kind)
    if existed and before is not None:
        size = len(before.encode("utf-8"))
        change.size = size
        if size > MAX_FILE_BYTES:
            change.skipped_reason = (
                f"file is {size} bytes, larger than the {MAX_FILE_BYTES}-byte checkpoint limit"
            )
        else:
            files = directory / FILES_DIRNAME
            files.mkdir(parents=True, exist_ok=True)
            saved_name = f"{len(group.changes):04d}-{_safe_name(Path(path).name)}"
            try:
                atomic_write_text(files / saved_name, before)
                change.saved = saved_name
            except OSError as exc:  # noqa: BLE001 - a failed save must not fail the write
                change.skipped_reason = f"could not save the previous content: {exc}"

    group.changes.append(change)
    try:
        _write_manifest(directory, group)
    except OSError as exc:  # noqa: BLE001
        logger.warning("could not write checkpoint manifest for %s: %s", session_id, exc)
        return None
    return change


# ── rollback ─────────────────────────────────────────────────────────────────────────────


def rollback(session_id: str, *, turns: int = 1) -> RollbackResult:
    """Restore the last ``turns`` turn groups of ``session_id`` and drop them.

    Files the agent modified are put back to the way they were, files it created are removed,
    and files it deleted are restored. Everything happens newest group first, so a file edited
    in two turns ends at its oldest saved state. A group whose saved copy is missing (too
    large, or lost) is still removed but reported under ``skipped``.
    """
    result = RollbackResult(turns=max(1, turns))
    groups = _groups(session_id)
    if not groups:
        return result
    selected = groups[-result.turns :]
    for group in reversed(selected):
        _rollback_group(session_id, group, result)
        _remove_group(session_id, group.turn)
        result.restored_groups.append(group.turn)
    result.restored_groups.reverse()
    return result


def _rollback_group(session_id: str, group: TurnGroup, result: RollbackResult) -> None:
    """Undo every change in ``group``, newest entry first."""
    directory = _turn_dir(session_id, group.turn)
    for change in reversed(group.changes):
        target = Path(change.path)
        if change.kind == "created":
            # The agent made the file this turn: rolling back means it goes away.
            try:
                if target.is_dir():
                    shutil.rmtree(target, ignore_errors=True)
                elif target.exists():
                    target.unlink()
            except OSError as exc:  # noqa: BLE001 - report and keep going
                result.skipped.append((change.path, f"could not remove: {exc}"))
                continue
            result.removed.append(change.path)
            continue
        if change.saved is None:
            reason = change.skipped_reason or "no saved copy of the previous content"
            result.skipped.append((change.path, reason))
            continue
        saved = directory / FILES_DIRNAME / change.saved
        try:
            content = saved.read_text(encoding="utf-8")
        except OSError as exc:  # noqa: BLE001
            result.skipped.append((change.path, f"could not read the saved copy: {exc}"))
            continue
        try:
            atomic_write_text(target, content)
        except OSError as exc:  # noqa: BLE001
            result.skipped.append((change.path, f"could not restore: {exc}"))
            continue
        result.restored.append(change.path)


def _remove_group(session_id: str, turn: int) -> None:
    shutil.rmtree(_turn_dir(session_id, turn), ignore_errors=True)


# ── listing ──────────────────────────────────────────────────────────────────────────────


def list_checkpoints(session_id: str) -> list[TurnGroup]:
    """Every stored turn group of ``session_id``, oldest first (for ``/checkpoints``)."""
    return _groups(session_id)


def total_size(session_id: str) -> int:
    """Bytes the checkpoint store of ``session_id`` occupies on disk."""
    root = session_dir(session_id)
    if not root.is_dir():
        return 0
    total = 0
    for path in root.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total


# ── pruning ──────────────────────────────────────────────────────────────────────────────


def prune_checkpoints(
    config: dict[str, Any],
    *,
    session_ids: list[str] | None = None,
    now: float | None = None,
    max_bytes: int | None = None,
) -> list[str]:
    """Trim the checkpoint store following ``sessions.retention_days`` and the size cap.

    Two rules, both best effort:

    * every checkpoint *group* older than ``sessions.retention_days`` is deleted (the same age
      the session database prunes at), and
    * when the whole store is over ``checkpoints.max_bytes`` the oldest groups are deleted
      until it fits.

    A session whose own row has already been pruned by the database is dropped entirely:
    ``session_ids`` is the list of sessions that still exist, and any store directory not in
    it belongs to a session that is gone. Returns the session ids whose store was emptied.
    """
    if session_ids is not None:
        return _prune_missing_sessions(session_ids)

    retention_days = float(get_path(config, "sessions.retention_days", 90) or 0)
    limit = (
        max_bytes
        if max_bytes is not None
        else int(get_path(config, "checkpoints.max_bytes", 100_000_000) or 0)
    )
    moment = time.time() if now is None else now
    cutoff = moment - retention_days * 86400 if retention_days > 0 else None
    emptied: list[str] = []
    for directory in _all_session_dirs():
        _prune_session_dir(directory, cutoff=cutoff, limit=limit, emptied=emptied)
    return emptied


def _all_session_dirs() -> list[Path]:
    root = get_checkpoints_dir()
    return [entry for entry in root.iterdir() if entry.is_dir()] if root.is_dir() else []


def _prune_missing_sessions(session_ids: list[str]) -> list[str]:
    """Drop the store of every session that no longer exists in the database."""
    alive = {_safe_name(session_id) for session_id in session_ids}
    emptied = []
    for directory in _all_session_dirs():
        if directory.name not in alive:
            shutil.rmtree(directory, ignore_errors=True)
            emptied.append(directory.name)
    return emptied


def _prune_session_dir(directory: Path, *, cutoff: float | None, limit: int, emptied: list[str]) -> None:
    removed = False
    for entry in sorted(directory.iterdir(), key=lambda path: path.name):
        if not entry.is_dir() or not entry.name.startswith(TURN_PREFIX):
            continue
        group = _read_manifest(entry)
        if cutoff is not None and group is not None and group.created_at and group.created_at < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
            removed = True
    if limit > 0 and _dir_size(directory) > limit:
        removed = _trim_to_size(directory, limit) or removed
    if removed and not any(
        child.is_dir() and child.name.startswith(TURN_PREFIX) for child in directory.iterdir()
    ):
        shutil.rmtree(directory, ignore_errors=True)
        emptied.append(directory.name)


def _trim_to_size(directory: Path, limit: int) -> bool:
    """Delete oldest turn groups until ``directory`` fits in ``limit`` bytes."""
    turns = sorted(
        (entry for entry in directory.iterdir() if entry.is_dir() and entry.name.startswith(TURN_PREFIX)),
        key=lambda path: path.name,
    )
    removed = False
    for entry in turns:
        if _dir_size(directory) <= limit:
            break
        shutil.rmtree(entry, ignore_errors=True)
        removed = True
    return removed


def _dir_size(directory: Path) -> int:
    total = 0
    for path in directory.rglob("*"):
        if path.is_file():
            try:
                total += path.stat().st_size
            except OSError:
                continue
    return total
