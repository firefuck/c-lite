"""``image_generate``: draw or edit a picture through a configured ``ImageProvider``.

The tool is offered only when a provider is registered (``check_fn``), so the model is never
told it can make images when there is no backend. The provider returns bytes; this tool saves
them under the session's working directory and returns the file paths, because the agent's
conversation carries text, not pictures.

Every path goes through ``write_denied_reason`` like any other file the agent writes, and the
prompt the model wrote is not echoed back as instructions.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from clite.tools.context import ToolContext
from clite.tools.file_safety import write_denied_reason
from clite.tools.image_gen import GeneratedImage, get_image_provider, has_image_provider
from clite.tools.registry import registry, tool_error, tool_result

MAX_PROMPT_CHARS = 4000
MAX_COUNT = 4
DEFAULT_OUTPUT_DIR = "generated-images"
_EXTENSION = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}
_SLUG = re.compile(r"[^a-z0-9]+")

IMAGE_GENERATE_SCHEMA = {
    "name": "image_generate",
    "description": (
        "Create an image from a text description (and optionally edit an existing one) and save "
        "it to a file. Returns the path(s) of the saved image(s). Use it when the user asks for a "
        "picture, a diagram or an illustration."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "prompt": {"type": "string", "description": "What the image should show."},
            "size": {"type": "string", "description": "Requested size as WIDTHxHEIGHT (e.g. 1024x1024); omit for the provider's default."},
            "count": {"type": "integer", "description": f"How many images to make (default 1, max {MAX_COUNT})."},
            "output_name": {"type": "string", "description": "Base file name without extension; defaults to a slug of the prompt."},
        },
        "required": ["prompt"],
    },
}


def _slug(prompt: str) -> str:
    cleaned = _SLUG.sub("-", prompt.lower()).strip("-")
    return (cleaned[:60] or "image").strip("-")


def _resolve_output(ctx: ToolContext, output_name: str, extension: str, index: int, count: int) -> Path:
    base = ctx.cwd or "."
    name = output_name.strip() or ""
    stem = _slug(name) if name else ""
    if not stem:
        stem = "image"
    suffix = "" if count == 1 else f"-{index + 1}"
    directory = Path(base) / DEFAULT_OUTPUT_DIR
    return directory / f"{stem}{suffix}{extension}"


def _image_extension(image: GeneratedImage) -> str:
    return _EXTENSION.get(image.media_type, ".png")


def image_generate_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        return tool_error("prompt is required; describe the image to make")
    if len(prompt) > MAX_PROMPT_CHARS:
        return tool_error(f"prompt is {len(prompt):,} characters; keep it under {MAX_PROMPT_CHARS:,}")
    size = str(args.get("size") or "").strip()
    try:
        count = int(args.get("count") or 1)
    except (TypeError, ValueError):
        return tool_error("count must be an integer")
    count = min(max(1, count), MAX_COUNT)

    provider = get_image_provider()
    if provider is None:
        return tool_error(
            "no image generation provider is configured; enable an image-generation plugin "
            "(e.g. image-gen-openai) or set image.provider in config.yaml")

    if size and provider.supported_sizes and size not in provider.supported_sizes:
        allowed = ", ".join(provider.supported_sizes)
        return tool_error(f"size {size!r} is not supported by {provider.name}; use one of: {allowed}")

    try:
        images = provider.generate(prompt, size=size, count=count)
    except Exception as exc:  # noqa: BLE001 - the model gets the error and can react
        return tool_error(f"image generation failed: {type(exc).__name__}: {exc}")
    if not images:
        return tool_error("the provider returned no images; try a different prompt")

    output_name = str(args.get("output_name") or "").strip()
    saved: list[dict[str, Any]] = []
    for index, image in enumerate(images[:count]):
        extension = _image_extension(image)
        target = _resolve_output(ctx, output_name or _slug(prompt), extension, index, len(images))
        denied = write_denied_reason(target)
        if denied:
            return tool_error(f"Refused to write {target}: {denied}.")
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(image.data)
        except OSError as exc:
            return tool_error(f"could not write {target}: {exc}")
        entry: dict[str, Any] = {"path": str(target), "media_type": image.media_type, "bytes": len(image.data)}
        if image.metadata.get("revised_prompt"):
            entry["revised_prompt"] = image.metadata["revised_prompt"]
        saved.append(entry)

    return tool_result(provider=provider.name, images=saved)


def _image_generation_available() -> bool:
    return has_image_provider()


registry.register(
    "image_generate", "vision", IMAGE_GENERATE_SCHEMA, image_generate_tool,
    emoji="🎨", parallel="never", check_fn=_image_generation_available,
)
