"""``clite serve``, ``clite dashboard`` and ``clite serve token``: the backend and its tokens.

There is deliberately no ``--token`` option: command-line arguments are visible to every local
user. A parent process or a person who wants a fixed token sets ``CLITE_SESSION_TOKEN``.

Named tokens are the other way in: they outlive the process that made them, so another device
can be let in and cut off again without restarting anything. ``clite serve token`` manages them.
"""

from __future__ import annotations

import argparse

from clite.core.brand import SESSION_TOKEN_ENV
from clite.core.config import config_get

TOKEN_NOTE = (
    f"The session token is read from {SESSION_TOKEN_ENV}. Without it a new one is generated "
    "and the dashboard URL that carries it is printed. For a token that outlives this process, "
    "see `clite serve token create`."
)


def run_serve(args: argparse.Namespace) -> int:
    from clite.server.run import serve

    host = args.host or str(config_get("server.host", "127.0.0.1"))
    port = args.port if args.port is not None else int(config_get("server.port", 0) or 0)
    return serve(
        host,
        port,
        open_browser=getattr(args, "open_browser", False),
        tls_certfile=getattr(args, "tls_cert", None),
        tls_keyfile=getattr(args, "tls_key", None),
        allow_insecure=getattr(args, "insecure", False),
    )


# ── named tokens ─────────────────────────────────────────────────────────────────────────


def run_token_create(args: argparse.Namespace) -> int:
    from clite.server.tokens import TokenError, get_token_store

    try:
        record, secret = get_token_store().create(args.name, ttl_days=args.days)
    except TokenError as exc:
        print(exc)
        return 1
    # The only time the value is ever shown. It is stored as a hash and cannot be read again.
    print(f"Token {record.name!r} created. Copy it now; it is not stored and cannot be shown again.")
    print(secret)
    if record.expires_at is not None:
        print(f"It expires {_when(record.expires_at)}.")
    return 0


def run_token_list(args: argparse.Namespace) -> int:
    from clite.server.tokens import get_token_store

    records = get_token_store().list()
    if not records:
        print("No named tokens. Create one with `clite serve token create <name>`.")
        return 0
    for record in records:
        expires = _when(record.expires_at) if record.expires_at else "never"
        used = _when(record.last_used_at) if record.last_used_at else "never"
        state = "expired" if record.expired() else "active"
        print(f"{record.name:<24} {state:<8} expires: {expires:<20} last used: {used}")
    return 0


def run_token_revoke(args: argparse.Namespace) -> int:
    from clite.server.tokens import get_token_store

    if not get_token_store().revoke(args.name):
        print(f"No token named {args.name!r}.")
        return 1
    print(f"Revoked {args.name!r}. A client already connected with it is cut off on its next message.")
    return 0


def _when(timestamp: float) -> str:
    import time

    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


# ── registration ─────────────────────────────────────────────────────────────────────────


def _add_serving_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", help="address to bind (default 127.0.0.1)")
    parser.add_argument("--port", type=int, help="port to bind; 0 picks a free one and reports it on stdout")
    parser.add_argument("--tls-cert", help="PEM certificate; required to bind beyond loopback")
    parser.add_argument("--tls-key", help="PEM private key for --tls-cert")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="allow binding beyond loopback without TLS (the token would cross the network in clear text)",
    )


def _add_token_commands(serve: argparse.ArgumentParser) -> None:
    tokens = serve.add_subparsers(dest="serve_action", metavar="token")
    token = tokens.add_parser("token", help="create, list or revoke named tokens")
    actions = token.add_subparsers(dest="token_action", required=True)
    create = actions.add_parser("create", help="make a token and print it once")
    create.add_argument("name")
    create.add_argument("--days", type=float, default=None, help="expire after this many days")
    create.set_defaults(handler=run_token_create)
    listing = actions.add_parser("list", help="show the tokens and when they were last used")
    listing.set_defaults(handler=run_token_list)
    revoke = actions.add_parser("revoke", help="drop a token; a live connection using it is cut off")
    revoke.add_argument("name")
    revoke.set_defaults(handler=run_token_revoke)


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    serve = subparsers.add_parser(
        "serve", help="run the headless backend (for the desktop app or a remote client)", epilog=TOKEN_NOTE
    )
    _add_serving_options(serve)
    _add_token_commands(serve)
    serve.set_defaults(handler=run_serve, open_browser=False)

    dashboard = subparsers.add_parser(
        "dashboard", help="run the backend and open the web dashboard", epilog=TOKEN_NOTE
    )
    _add_serving_options(dashboard)
    dashboard.add_argument(
        "--no-open", dest="open_browser", action="store_false", help="do not open a browser"
    )
    dashboard.set_defaults(handler=run_serve, open_browser=True)
