"""``text_to_speech``: speak text into an audio file through a configured ``SpeechProvider``.

The tool stops at the file. Putting it in front of the user is ``send_file``'s job, so spoken
output travels the same path, and is subject to the same checks, as any other file the agent
makes -- and a surface with no chat behind it still ends up with a playable file.

The tool is offered only when a speech provider is configured (``check_fn``), so the model is
never told it can speak on a machine where nothing can.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from clite.tools.context import ToolContext
from clite.tools.file_safety import write_denied_reason
from clite.tools.registry import registry, tool_error, tool_result
from clite.tools.speech import (
    get_speech_provider,
    has_speech_provider,
    speech_limits,
    speech_settings,
)

#: Where spoken files land, relative to the session's working directory.
DEFAULT_OUTPUT_DIR = "spoken"
_SLUG = re.compile(r"[^a-z0-9]+")

TEXT_TO_SPEECH_SCHEMA = {
    "name": "text_to_speech",
    "description": (
        "Turn text into an audio file with the configured speech provider and return the path. "
        "Send the file to the user with send_file. Use it when the user asks to hear something, "
        "or when a reply is meant to be listened to rather than read."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "What should be said."},
            "voice": {
                "type": "string",
                "description": "Voice id; omit to use the configured default.",
            },
            "output_name": {
                "type": "string",
                "description": "Base file name without extension; defaults to a slug of the text.",
            },
        },
        "required": ["text"],
    },
}


def _slug(text: str) -> str:
    cleaned = _SLUG.sub("-", text.lower()).strip("-")
    return (cleaned[:60] or "speech").strip("-")


def _resolve_output(ctx: ToolContext, output_name: str, extension: str) -> Path:
    stem = _slug(output_name) if output_name.strip() else "speech"
    return Path(ctx.cwd or ".") / DEFAULT_OUTPUT_DIR / f"{stem}{extension}"


def text_to_speech_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    text = str(args.get("text") or "").strip()
    if not text:
        return tool_error("text is required; say what should be spoken")
    # Zero is the configuration saying there is no ceiling; the shipped default is 4000, just
    # under the 4096 characters the OpenAI speech API takes. A provider bills per character, so
    # an over-long text is refused rather than trimmed or paid for.
    max_chars = int(speech_limits()["max_chars"])
    if max_chars and len(text) > max_chars:
        return tool_error(f"text is {len(text):,} characters; keep it under {max_chars:,}")

    provider = get_speech_provider()
    if provider is None:
        return tool_error(
            "no speech provider is configured; enable a speech plugin (e.g. speech-openai) or "
            "set speech.speech.provider in config.yaml"
        )

    settings = speech_settings()
    voice = str(args.get("voice") or settings["voice"])
    model = settings["model"]
    name = str(args.get("output_name") or "").strip() or _slug(text)  # what the schema promises
    target = _resolve_output(ctx, name, f".{provider.output_format}")
    denied = write_denied_reason(target)
    if denied:
        return tool_error(f"Refused to write {target}: {denied}.")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        written = provider.synthesize(text, target, voice=voice, model=model)
    except Exception as exc:  # noqa: BLE001 - the model gets the error and can react
        return tool_error(f"speech synthesis failed: {type(exc).__name__}: {exc}")
    try:
        size = written.stat().st_size
    except OSError as exc:
        return tool_error(f"the provider reported {written} but it cannot be read: {exc}")
    return tool_result(
        provider=provider.name,
        path=str(written),
        bytes=size,
        hint="Send it to the user with send_file.",
    )


def _speech_available() -> bool:
    return has_speech_provider()


registry.register(
    "text_to_speech",
    "messaging",
    TEXT_TO_SPEECH_SCHEMA,
    text_to_speech_tool,
    emoji="🔊",
    parallel="never",
    check_fn=_speech_available,
)
