"""Starting the backend: bind, announce readiness, serve.

The contract with whoever spawned this process (the desktop app, a script, a test):

* the session token comes from ``CLITE_SESSION_TOKEN`` if set, so the parent already knows
  it and it never appears on a command line; otherwise one is generated and printed;
* once the socket is bound, exactly one line ``CLITE_BACKEND_READY port=<n>`` is written to
  stdout. With ``--port 0`` this is how the parent learns the port.
"""

from __future__ import annotations

import os
import secrets
import socket
import sys
import threading
import webbrowser
from collections.abc import Callable
from typing import Any, TextIO

from clite.core.brand import BACKEND_READY_SENTINEL, SESSION_TOKEN_ENV

LOOPBACK = ("127.0.0.1", "localhost", "::1")


def bind_socket(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(128)
    sock.set_inheritable(True)
    return sock


def dashboard_url(host: str, port: int, token: str) -> str:
    shown = "127.0.0.1" if host in ("0.0.0.0", "::") else host  # noqa: S104 - display only
    # The token rides in the fragment: it is never sent to a server or written to a log.
    return f"http://{shown}:{port}/#token={token}"


def serve(host: str = "127.0.0.1", port: int = 0, *, token: str | None = None, open_browser: bool = False,
          out: TextIO | None = None, client_factory: Callable[[], Any] | None = None,
          on_ready: Callable[[int, str, Any], None] | None = None) -> int:
    import uvicorn

    from clite.server.app import create_app

    out = out or sys.stdout
    inherited = os.environ.get(SESSION_TOKEN_ENV, "").strip()
    token = token or inherited or secrets.token_urlsafe(32)
    sock = bind_socket(host, port)
    bound_port = sock.getsockname()[1]

    server = uvicorn.Server(uvicorn.Config(create_app(token, client_factory=client_factory), log_level="warning",
                                           access_log=False, lifespan="off"))
    print(f"{BACKEND_READY_SENTINEL} port={bound_port}", file=out, flush=True)
    url = dashboard_url(host, bound_port, token)
    if not inherited:
        # Nobody handed us a token, so a person started this: show them how to get in.
        print(f"Dashboard: {url}", file=sys.stderr, flush=True)
    if host not in LOOPBACK:
        print(f"WARNING: listening on {host}. Anyone who can reach this port and has the token controls the agent.",
              file=sys.stderr, flush=True)
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    if on_ready is not None:
        on_ready(bound_port, token, server)
    try:
        server.run(sockets=[sock])
    finally:
        sock.close()
    return 0
