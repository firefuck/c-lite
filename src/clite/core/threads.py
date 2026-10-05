"""Threads that carry the caller's context.

A new thread starts with an empty context: a home bound with ``home_scope`` or secrets bound
with ``secret_scope`` are not visible in it. Any thread that does work on behalf of a session
(a turn, a scheduler tick, a platform's polling loop) must therefore be started here, so the
profile that started the work is the profile the work runs under.
"""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Callable
from typing import Any


def start_thread(target: Callable[..., Any], *args: Any, name: str, daemon: bool = True) -> threading.Thread:
    """Start ``target(*args)`` on a new thread, inside a copy of the calling context."""
    context = contextvars.copy_context()
    thread = threading.Thread(target=context.run, args=(target, *args), name=name, daemon=daemon)
    thread.start()
    return thread
