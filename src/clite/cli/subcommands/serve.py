"""``clite serve`` and ``clite dashboard``: the HTTP + WebSocket backend."""

from __future__ import annotations

import argparse

from clite.core.config import config_get


def run_serve(args: argparse.Namespace) -> int:
    from clite.server.run import serve

    host = args.host or str(config_get("server.host", "127.0.0.1"))
    port = args.port if args.port is not None else int(config_get("server.port", 0) or 0)
    return serve(host, port, token=args.token, open_browser=getattr(args, "open_browser", False))


def register(subparsers: argparse._SubParsersAction) -> None:
    serve = subparsers.add_parser("serve", help="run the headless backend (for the desktop app or a remote client)")
    serve.add_argument("--host", help="address to bind (default 127.0.0.1)")
    serve.add_argument("--port", type=int, help="port to bind; 0 picks a free one and reports it on stdout")
    serve.add_argument("--token", help="session token (default: CLITE_SESSION_TOKEN, else generated)")
    serve.set_defaults(handler=run_serve, open_browser=False)

    dashboard = subparsers.add_parser("dashboard", help="run the backend and open the web dashboard")
    dashboard.add_argument("--host")
    dashboard.add_argument("--port", type=int)
    dashboard.add_argument("--token")
    dashboard.add_argument("--no-open", dest="open_browser", action="store_false", help="do not open a browser")
    dashboard.set_defaults(handler=run_serve, open_browser=True)
