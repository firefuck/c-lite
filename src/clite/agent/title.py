"""Session titles: a short label generated after the first exchange."""

from __future__ import annotations

import logging
import re
import threading
from typing import TYPE_CHECKING

from clite.core.threads import start_thread
from clite.providers.auxiliary import call_auxiliary

if TYPE_CHECKING:
    from clite.agent.agent import AIAgent

logger = logging.getLogger("clite.agent.title")

MAX_TITLE_CHARS = 60
_PROMPT = (
    "Write a title of at most six words for a conversation that starts with the message below. "
    "Reply with the title only: no quotes, no trailing punctuation.\n\n<message>\n{message}\n</message>"
)


def fallback_title(user_text: str) -> str:
    """A title cut from the user's own words, for when no model is available to write one."""
    text = " ".join(user_text.split())
    if len(text) > MAX_TITLE_CHARS:
        text = text[:MAX_TITLE_CHARS].rsplit(" ", 1)[0] + "…"
    return text or "Untitled session"


def clean_title(raw: str) -> str:
    title = " ".join(raw.strip().splitlines()[0].split()) if raw.strip() else ""
    title = re.sub(r"^(title\s*:\s*)", "", title, flags=re.IGNORECASE).strip("\"'`*# .")
    return title[:MAX_TITLE_CHARS]


def generate_title(agent: AIAgent, user_text: str) -> str:
    """Title for the session. Uses the auxiliary model; falls back to the user's words."""
    if agent.route.api_mode != "mock":
        try:
            raw = call_auxiliary(
                "title_generation", [{"role": "user", "content": _PROMPT.format(message=user_text[:2000])}],
                main_route=agent.route, client=agent.client, max_tokens=40, timeout=30.0, config=agent.config,
            )
            title = clean_title(raw)
            if title:
                return title
        except Exception as exc:  # noqa: BLE001 - a title is never worth failing for
            logger.debug("title generation failed: %s", exc)
    return fallback_title(user_text)


def generate_title_async(agent: AIAgent, user_text: str) -> threading.Thread:
    """Generate and store the title off the turn's thread; the reply is not held up for it."""

    def work() -> None:
        try:
            title = generate_title(agent, user_text)
            if agent.db is not None:
                stored = agent.db.set_title(agent.session_id, title, source="auto")
                agent.callbacks.emit("on_status", "title", stored)
        except Exception:  # noqa: BLE001
            logger.debug("could not store session title", exc_info=True)

    return start_thread(work, name="clite-title")
