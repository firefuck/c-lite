"""In-session task list, owned by the agent and edited through the ``todo`` tool."""

from __future__ import annotations

import threading
from typing import Any

STATUSES = ("pending", "in_progress", "completed", "cancelled")
_MARKS = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]", "cancelled": "[~]"}
MAX_ITEMS = 100


class TodoStore:
    def __init__(self) -> None:
        self._items: list[dict[str, str]] = []
        self._lock = threading.Lock()

    def read(self) -> list[dict[str, str]]:
        with self._lock:
            return [dict(item) for item in self._items]

    def write(self, todos: list[dict[str, Any]], merge: bool = False) -> list[dict[str, str]]:
        """Replace the list, or with ``merge`` update items by id and append new ones."""
        cleaned = [self._clean(item, index) for index, item in enumerate(todos)]
        with self._lock:
            if merge:
                by_id = {item["id"]: item for item in self._items}
                for item in cleaned:
                    if item["id"] in by_id:
                        by_id[item["id"]].update(item)
                    else:
                        self._items.append(item)
            else:
                self._items = cleaned
            self._items = self._items[:MAX_ITEMS]
            return [dict(item) for item in self._items]

    @staticmethod
    def _clean(item: dict[str, Any], index: int) -> dict[str, str]:
        if not isinstance(item, dict):
            raise ValueError("each todo must be an object with id, content and status")
        content = str(item.get("content") or "").strip()
        if not content:
            raise ValueError("each todo needs content")
        status = str(item.get("status") or "pending")
        if status not in STATUSES:
            raise ValueError(f"invalid status {status!r}; use one of {', '.join(STATUSES)}")
        return {"id": str(item.get("id") or index + 1), "content": content, "status": status}

    def summary(self) -> dict[str, int]:
        items = self.read()
        return {status: sum(1 for item in items if item["status"] == status) for status in STATUSES} | {"total": len(items)}

    def format_active(self) -> str:
        """Unfinished items as text, re-attached after a compression so the plan survives it."""
        active = [item for item in self.read() if item["status"] in ("pending", "in_progress")]
        if not active:
            return ""
        lines = [f"- {_MARKS[item['status']]} {item['id']}. {item['content']}" for item in active]
        return "[Your task list was preserved across the context summary:]\n" + "\n".join(lines)
