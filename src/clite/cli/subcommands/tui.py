"""``clite tui``: the Node terminal interface, which talks to this package over JSON-RPC."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from clite.core.brand import ENV_PREFIX

BUNDLE_NAME = "clite-tui.mjs"


def find_tui_bundle() -> Path | None:
    """The built TUI: an explicit directory, the copy shipped in the package, or a checkout."""
    package_root = Path(__file__).resolve().parents[2]
    candidates = [
        Path(os.environ.get(f"{ENV_PREFIX}_TUI_DIR", "")) / BUNDLE_NAME if os.environ.get(f"{ENV_PREFIX}_TUI_DIR") else None,
        package_root / "tui_dist" / BUNDLE_NAME,
        package_root.parents[1] / "ui-tui" / "dist" / BUNDLE_NAME,
    ]
    return next((path for path in candidates if path is not None and path.is_file()), None)


def tui_arguments(options: dict[str, Any]) -> list[str]:
    """Chat options (see ``chat.session_options``) as arguments for the TUI entry point."""
    arguments: list[str] = []
    if options.get("session_id"):
        arguments += ["--resume", str(options["session_id"])]
    if options.get("model"):
        arguments += ["--model", str(options["model"])]
    if options.get("provider"):
        arguments += ["--provider", str(options["provider"])]
    if options.get("yolo"):
        arguments.append("--yolo")
    return arguments


def launch_tui(arguments: list[str], *, fallback_options: dict[str, Any] | None = None) -> int:
    """Run the TUI on this terminal. Without Node.js or the bundle, say so and start the
    classic CLI instead, so the command the user typed still gets them a chat."""
    node = shutil.which("node")
    bundle = find_tui_bundle()
    if node is None or bundle is None:
        missing = "Node.js (version 22 or newer)" if node is None else "the TUI bundle (build it with `npm run build` in ui-tui/)"
        print(f"The TUI needs {missing}. Starting the classic CLI instead.", file=sys.stderr)
        from clite.cli.repl import Repl

        return Repl(**(fallback_options or {})).run()
    env = {**os.environ, f"{ENV_PREFIX}_PYTHON": sys.executable}
    return subprocess.call([node, str(bundle), *arguments], env=env)  # noqa: S603


def run_tui(args: argparse.Namespace) -> int:
    return launch_tui([arg for arg in getattr(args, "extra_args", []) if arg != "--"])


def register(subparsers: argparse._SubParsersAction) -> None:
    # Everything after `tui` belongs to the TUI, including -h: the TUI prints its own help,
    # which lists the options it really takes. (argparse.REMAINDER cannot do this: it stops
    # at the first argument that looks like an option.)
    parser = subparsers.add_parser("tui", help="start the terminal UI (needs Node.js)", add_help=False)
    parser.set_defaults(handler=run_tui, accepts_extra_args=True, extra_args=[])
