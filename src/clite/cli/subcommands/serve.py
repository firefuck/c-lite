"""``clite serve`` and ``clite dashboard``: the HTTP + WebSocket backend.

There is deliberately no ``--token`` option: command-line arguments are visible to every local
user. A parent process or a person who wants a fixed token sets ``CLITE_SESSION_TOKEN``.
"""

from __future__ import annotations

import argparse

from clite.core.brand import SESSION_TOKEN_ENV
from clite.core.config import config_get

TOKEN_NOTE = (f"The session token is read from {SESSION_TOKEN_ENV}. Without it a new one is generated "
              "and the dashboard URL that carries it is printed.")


def run_serve(args: argparse.Namespace) -> int:
    from clite.server.run import serve

    host = args.host or str(config_get("server.host", "127.0.0.1"))
    port = args.port if args.port is not None else int(config_get("server.port", 0) or 0)
    return serve(host, port, open_browser=getattr(args, "open_browser", False))


def register(subparsers: argparse._SubParsersAction) -> None:
    serve = subparsers.add_parser("serve", help="run the headless backend (for the desktop app or a remote client)",
                                  epilog=TOKEN_NOTE)
    serve.add_argument("--host", help="address to bind (default 127.0.0.1)")
    serve.add_argument("--port", type=int, help="port to bind; 0 picks a free one and reports it on stdout")
    serve.set_defaults(handler=run_serve, open_browser=False)

    dashboard = subparsers.add_parser("dashboard", help="run the backend and open the web dashboard", epilog=TOKEN_NOTE)
    dashboard.add_argument("--host")
    dashboard.add_argument("--port", type=int)
    dashboard.add_argument("--no-open", dest="open_browser", action="store_false", help="do not open a browser")
    dashboard.set_defaults(handler=run_serve, open_browser=True)
