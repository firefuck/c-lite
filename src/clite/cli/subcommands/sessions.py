"""``clite sessions``: browse, search, export and prune stored conversations."""

from __future__ import annotations

import argparse
import json
import sys
import time

from clite.agent.messages import content_text
from clite.core.config import config_get
from clite.state.db import get_session_db


def _when(timestamp: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp)) if timestamp else "-"


def _find(reference: str):
    row = get_session_db().find_session(reference)
    if row is None:
        print(f"No session matches {reference!r}.")
    return row


def run_list(args: argparse.Namespace) -> int:
    rows = get_session_db().list_sessions(limit=args.limit, sources=[args.source] if args.source else None,
                                          include_archived=args.all, include_children=args.all)
    if not rows:
        print("No sessions yet.")
        return 0
    for row in rows:
        print(f"{row['id']}  {_when(row.get('last_activity_at') or row['started_at'])}  {row['source']:<8} "
              f"{row['message_count']:>4} msgs  {row.get('model') or '':<24.24} {row.get('title') or ''}")
    return 0


def run_show(args: argparse.Namespace) -> int:
    row = _find(args.session)
    if row is None:
        return 1
    print(f"# {row.get('title') or row['id']}  ({row['source']}, {row.get('model')}, started {_when(row['started_at'])})\n")
    for message in get_session_db().get_messages(row["id"], include_inactive=args.all):
        role, text = message["role"], content_text(message.get("content"))
        if role == "tool":
            print(f"[tool {message.get('name')}] {text[:500]}\n")
            continue
        calls = ", ".join(call["function"]["name"] for call in message.get("tool_calls") or [])
        print(f"{role.upper()}: {text}" + (f"\n  (called: {calls})" if calls else "") + "\n")
    return 0


def run_rename(args: argparse.Namespace) -> int:
    row = _find(args.session)
    if row is None:
        return 1
    print(f"Title: {get_session_db().set_title(row['id'], ' '.join(args.title))}")
    return 0


def run_delete(args: argparse.Namespace) -> int:
    row = _find(args.session)
    if row is None:
        return 1
    get_session_db().delete_session(row["id"])
    print(f"Deleted {row['id']}.")
    return 0


def run_export(args: argparse.Namespace) -> int:
    row = _find(args.session)
    if row is None:
        return 1
    db = get_session_db()
    messages = [{key: value for key, value in message.items() if key != "_row_id"} for message in db.get_messages(row["id"])]
    payload = json.dumps({"session": {key: row[key] for key in ("id", "source", "model", "provider", "title", "started_at")},
                          "messages": messages}, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
        print(f"Exported {len(messages)} messages to {args.output}")
    else:
        sys.stdout.write(payload + "\n")
    return 0


def run_search(args: argparse.Namespace) -> int:
    hits = get_session_db().search_messages(" ".join(args.query), limit=args.limit)
    if not hits:
        print("No matches.")
        return 0
    for hit in hits:
        print(f"{hit['session_id']}  {_when(hit['timestamp'])}  {hit['role']:<9} {hit['snippet']}")
    return 0


def run_prune(args: argparse.Namespace) -> int:
    days = args.older_than if args.older_than is not None else float(config_get("sessions.retention_days", 90) or 90)
    db = get_session_db()
    if not args.yes:
        count = db.prune_sessions(days, dry_run=True)
        print(f"{count} session(s) with no activity for {days:g} days would be deleted (pinned sessions are kept). "
              "Re-run with --yes to delete them.")
        return 0
    print(f"Deleted {db.prune_sessions(days)} session(s).")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("sessions", help="list, show, search, export or delete sessions")
    parser.set_defaults(handler=run_list, limit=20, source=None, all=False)
    actions = parser.add_subparsers(dest="sessions_action")
    listing = actions.add_parser("list", help="list recent sessions")
    listing.add_argument("-n", "--limit", type=int, default=20)
    listing.add_argument("--source", help="only this platform (cli, cron, telegram, ...)")
    listing.add_argument("--all", action="store_true", help="include archived sessions and subagent sessions")
    listing.set_defaults(handler=run_list)
    show = actions.add_parser("show", help="print a session's messages")
    show.add_argument("session")
    show.add_argument("--all", action="store_true", help="include messages that were summarised away")
    show.set_defaults(handler=run_show)
    rename = actions.add_parser("rename", help="set a session's title")
    rename.add_argument("session")
    rename.add_argument("title", nargs="+")
    rename.set_defaults(handler=run_rename)
    delete = actions.add_parser("delete", help="delete a session")
    delete.add_argument("session")
    delete.set_defaults(handler=run_delete)
    export = actions.add_parser("export", help="write a session as JSON")
    export.add_argument("session")
    export.add_argument("-o", "--output")
    export.set_defaults(handler=run_export)
    search = actions.add_parser("search", help="full-text search across all sessions")
    search.add_argument("query", nargs="+")
    search.add_argument("-n", "--limit", type=int, default=20)
    search.set_defaults(handler=run_search)
    prune = actions.add_parser("prune", help="delete old sessions")
    prune.add_argument("--older-than", type=float, default=None, metavar="DAYS",
                       help="default: sessions.retention_days from config.yaml")
    prune.add_argument("--yes", action="store_true", help="delete; without it the command only counts")
    prune.set_defaults(handler=run_prune)
