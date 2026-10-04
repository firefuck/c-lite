"""``clite``: the command-line entry point.

Order matters at startup:

1. ``-p/--profile`` is applied first, before anything reads the home directory.
2. ``.env`` is loaded, then logging is set up for that home.
3. Subcommands are registered from ``clite.cli.subcommands`` and from enabled plugins.

With no subcommand, ``clite`` starts a chat.
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys

from clite import __version__
from clite.cli.subcommands import SUBCOMMAND_MODULES
from clite.core.brand import APP_NAME, DISPLAY_NAME
from clite.core.config import get_path, load_config
from clite.core.env import load_env
from clite.core.errors import CliteError, ConfigError, ProfileError
from clite.core.logging import setup_logging
from clite.core.profiles import apply_profile_override

logger = logging.getLogger("clite.cli")


def build_parser() -> argparse.ArgumentParser:
    from clite.cli.subcommands.chat import add_chat_arguments, run_chat

    parser = argparse.ArgumentParser(
        prog=APP_NAME,
        description=f"{DISPLAY_NAME}: a personal AI agent. Run without a command to start chatting.",
        epilog="Use -p/--profile NAME before any command to run it in another profile.",
    )
    parser.add_argument("--version", action="version", version=f"{DISPLAY_NAME} {__version__}")
    add_chat_arguments(parser)  # `clite -q "..."` works without typing `chat`
    parser.set_defaults(handler=run_chat)
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for name in SUBCOMMAND_MODULES:
        importlib.import_module(f"clite.cli.subcommands.{name}").register(subparsers)
    _register_plugin_commands(subparsers)
    return parser


def _register_plugin_commands(subparsers: argparse._SubParsersAction) -> None:
    """Subcommands contributed by enabled plugins. A broken plugin never breaks the CLI."""
    try:
        from clite.plugins.manager import ensure_plugins_loaded

        manager = ensure_plugins_loaded()
    except Exception:  # noqa: BLE001
        logger.warning("plugins could not be loaded for the CLI", exc_info=True)
        return
    builtin = set(subparsers.choices)
    for name, command in sorted(manager.cli_commands.items()):
        if name in builtin:
            logger.warning("plugin %s tried to replace the built-in command %r; ignored", command.plugin, name)
            continue
        try:
            parser = subparsers.add_parser(name, help=command.help)
            if command.setup is not None:
                command.setup(parser)
            parser.set_defaults(handler=command.handler)
        except Exception:  # noqa: BLE001
            logger.warning("plugin command %r could not be registered", name, exc_info=True)


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        arguments = apply_profile_override(arguments)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    load_env()
    try:
        config = load_config()
    except ConfigError as exc:
        # Still let `clite config edit` and `clite doctor` run so the user can fix the file.
        print(f"warning: {exc}", file=sys.stderr)
        config = {}
    setup_logging(str(get_path(config, "logging.level", "INFO")), max_size_mb=int(get_path(config, "logging.max_size_mb", 5)),
                  backup_count=int(get_path(config, "logging.backup_count", 3)))
    try:
        parser = build_parser()
        args, extra = parser.parse_known_args(arguments)
        if extra:
            # Only a command that forwards its arguments to another program (`clite tui`)
            # may receive options argparse does not know.
            if not getattr(args, "accepts_extra_args", False):
                parser.error(f"unrecognized arguments: {' '.join(extra)}")
            args.extra_args = extra
        return int(args.handler(args) or 0)
    except CliteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(file=sys.stderr)
        return 130
    except BrokenPipeError:
        return 0  # `clite sessions list | head`


if __name__ == "__main__":
    raise SystemExit(main())
