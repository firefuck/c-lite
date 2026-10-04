"""Redaction: keep credentials out of transcripts and logs.

Two layers: the exact values of every secret loaded from ``.env`` (certain), and shape-based
patterns for well-known key formats (best effort). Redaction is one-way; the caller never
needs the original back.
"""

from __future__ import annotations

import os
import re

from clite.core.env import loaded_secret_names

REDACTED = "[REDACTED]"
_MIN_SECRET_LENGTH = 8

_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),  # OpenAI / Anthropic / OpenRouter style
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"),  # GitHub tokens
    re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}"),  # Slack
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),  # AWS access key id
    re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}"),  # Google API key
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b"),  # Telegram bot token
    re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9_\-\.=]{16,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
]


def redact(text: str) -> str:
    """``text`` with known secret values and key-shaped strings replaced."""
    if not text:
        return text
    for name in loaded_secret_names():
        value = os.environ.get(name, "")
        if len(value) >= _MIN_SECRET_LENGTH and value in text:
            text = text.replace(value, REDACTED)
    for pattern in _PATTERNS:
        text = pattern.sub(lambda match: (match.group(1) + " " if match.lastindex else "") + REDACTED, text)
    return text
