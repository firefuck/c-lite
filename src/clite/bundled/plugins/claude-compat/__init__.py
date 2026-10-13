"""Claude compatibility plugin for C-lite.

Seamlessly loads and applies project guidelines written for Claude Code (CLAUDE.md)
when working in external codebases, folding them into C-lite's session turn context.
"""

from __future__ import annotations

from pathlib import Path


def _find_claude_instructions(cwd: Path) -> str | None:
    candidate = cwd / "CLAUDE.md"
    if candidate.is_file():
        try:
            content = candidate.read_text(encoding="utf-8").strip()
            if content:
                return content
        except OSError:
            pass
    return None


def register(ctx) -> None:
    def on_system_prompt(prompt: str, session_id: str | None = None, cwd: str | None = None) -> str:
        target_dir = Path(cwd) if cwd else Path.cwd()
        instructions = _find_claude_instructions(target_dir)
        if not instructions:
            return prompt

        banner = f"\n\n# Project Guidelines (from CLAUDE.md via claude-compat plugin)\n{instructions}\n"
        return prompt + banner

    ctx.register_hook("system_prompt", on_system_prompt)
