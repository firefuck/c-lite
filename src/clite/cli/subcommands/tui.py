"""``clite tui``: the Node terminal interface, which talks to this package over JSON-RPC."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

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


def run_tui(args: argparse.Namespace) -> int:
    node = shutil.which("node")
    bundle = find_tui_bundle()
    if node is None or bundle is None:
        missing = "Node.js (version 20 or newer)" if node is None else "the TUI bundle (build it with `npm run build` in ui-tui/)"
        print(f"The TUI needs {missing}. Starting the classic CLI instead.", file=sys.stderr)
        from clite.cli.repl import Repl

        return Repl().run()
    env = {**os.environ, f"{ENV_PREFIX}_PYTHON": sys.executable}
    extra = [arg for arg in getattr(args, "tui_args", []) if arg != "--"]
    return subprocess.call([node, str(bundle), *extra], env=env)  # noqa: S603


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("tui", help="start the terminal UI (needs Node.js)")
    parser.add_argument("tui_args", nargs=argparse.REMAINDER, help="arguments passed to the TUI")
    parser.set_defaults(handler=run_tui)
