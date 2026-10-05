"""Scan text that will be injected into the system prompt.

Context files, memory entries and skills all end up in front of the model with the authority
of the system prompt. Content from a cloned repository or a downloaded skill is untrusted, so
it is scanned before it is loaded. A hit blocks the content and says why; it does not try to
sanitise and continue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# (pattern, id). Deliberately specific: a false positive silently drops a user's file.
_PATTERNS: list[tuple[str, str]] = [
    (r"ignore\s+(all\s+)?(the\s+)?(previous|prior|above|earlier)\s+(instructions|prompts|rules)", "ignore_instructions"),
    (r"disregard\s+(all\s+|any\s+)?(your\s+|the\s+)?(previous\s+|prior\s+)?(instructions|rules|guidelines)", "disregard_rules"),
    (r"you\s+are\s+now\s+(?!able|ready|in\s+the|going)(a|an|the|in)\s", "role_hijack"),
    (r"do\s+not\s+(tell|inform|mention\s+(this\s+)?to)\s+the\s+user", "deception"),
    (r"(reveal|print|output|show)\s+(your\s+|the\s+)?(system\s+prompt|hidden\s+instructions)", "prompt_extraction"),
    (r"act\s+as\s+(if|though)\s+you\s+(have|had)\s+no\s+(restrictions|rules|guidelines)", "bypass_restrictions"),
    (r"<!--[^>]*(ignore|override|system\s*prompt|secret\s+instruction)[^>]*-->", "hidden_html_comment"),
    (r"<\s*div[^>]*display\s*:\s*none", "hidden_div"),
    (r"curl\s+[^\n]*\$\{?\w*(KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)", "exfil_curl"),
    (r"(curl|wget)\s+[^\n]*(-d|--data|--post-data)\s+[^\n]*\$\(\s*cat\s", "exfil_file"),
    (r"cat\s+[^\n]*(\.env\b|credentials|\.netrc|id_rsa|\.pgpass)", "read_secrets"),
    (r"base64\s+[^\n|]*\|\s*(curl|wget|nc)\b", "exfil_base64"),
    (r">>?\s*~?/?\.ssh/authorized_keys", "ssh_backdoor"),
]
_COMPILED = [(re.compile(pattern, re.IGNORECASE), name) for pattern, name in _PATTERNS]

# Characters that are invisible when rendered and are used to hide instructions.
_INVISIBLE = {
    "​": "zero_width_space", "‌": "zero_width_non_joiner", "‍": "zero_width_joiner",
    "⁠": "word_joiner", "﻿": "byte_order_mark",
    "‪": "bidi_embedding", "‫": "bidi_embedding", "‭": "bidi_override", "‮": "bidi_override",
    "⁦": "bidi_isolate", "⁧": "bidi_isolate", "⁨": "bidi_isolate",
}


@dataclass(frozen=True)
class Threat:
    id: str
    snippet: str


def scan_text(text: str) -> list[Threat]:
    """Threats found in ``text``; empty when it looks clean."""
    found: dict[str, Threat] = {}
    for char, name in _INVISIBLE.items():
        # A BOM at the very start of a file is an encoding artefact, not an attack.
        if char in (text[1:] if char == "﻿" else text):
            found.setdefault(f"invisible_unicode:{name}", Threat(f"invisible_unicode:{name}", repr(char)))
    for pattern, name in _COMPILED:
        match = pattern.search(text)
        if match and name not in found:
            found[name] = Threat(name, " ".join(match.group(0).split())[:80])
    return list(found.values())


def describe(threats: list[Threat]) -> str:
    return ", ".join(threat.id for threat in threats)
