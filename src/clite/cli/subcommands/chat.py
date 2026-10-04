"""``clite chat``: the interactive REPL, or one query with ``-q``. Also the default command."""

from __future__ import annotations

import argparse

from clite.core.errors import CliteError
from clite.state.db import get_session_db


def add_chat_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-q", "--query", help="run one prompt and exit (the answer goes to stdout)")
    parser.add_argument("-m", "--model", help="model for this run, optionally as provider:model")
    parser.add_argument("--provider", help="provider for this run")
    parser.add_argument("-t", "--toolsets", help="comma-separated toolsets for this run")
    parser.add_argument("-r", "--resume", metavar="SESSION", help="resume a session by id, id prefix or title")
    parser.add_argument("-c", "--continue", dest="continue_last", action="store_true", help="resume the most recent session")
    parser.add_argument("--yolo", action="store_true", help="skip command approval prompts")
    parser.add_argument("--max-turns", type=int, help="limit tool-calling iterations per turn")
    parser.add_argument("--json", action="store_true", help="with -q: print the full result as JSON")
    parser.add_argument("--quiet", action="store_true", help="with -q: print nothing but the answer")


def session_options(args: argparse.Namespace) -> dict:
    session_id = None
    if getattr(args, "resume", None):
        row = get_session_db().find_session(args.resume)
        if row is None:
            raise CliteError(f"no session matches {args.resume!r}; see `clite sessions list`")
        session_id = row["id"]
    elif getattr(args, "continue_last", False):
        row = get_session_db().latest_session(sources=["cli", "tui", "desktop"])
        if row is None:
            raise CliteError("there is no earlier session to continue")
        session_id = row["id"]
    model, provider = getattr(args, "model", None), getattr(args, "provider", None)
    if model and ":" in model and not provider:
        from clite.providers.model_switch import parse_model_input

        parsed_provider, parsed_model = parse_model_input(model)
        if parsed_provider:
            provider, model = parsed_provider, parsed_model
    toolsets = [name.strip() for name in args.toolsets.split(",") if name.strip()] if getattr(args, "toolsets", None) else None
    return {"session_id": session_id, "model": model, "provider": provider, "toolsets": toolsets,
            "yolo": bool(getattr(args, "yolo", False)), "max_turns": getattr(args, "max_turns", None)}


def run_chat(args: argparse.Namespace) -> int:
    from clite.cli.repl import Repl, run_single_query

    options = session_options(args)
    if args.query is not None:
        return run_single_query(args.query, as_json=args.json, quiet=args.quiet, **options)
    return Repl(**options).run()


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("chat", help="talk to the agent (default command)")
    add_chat_arguments(parser)
    parser.set_defaults(handler=run_chat)
