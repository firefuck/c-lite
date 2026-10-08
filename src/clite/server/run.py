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


def bind_refusal(
    host: str,
    *,
    tls_certfile: str | None = None,
    tls_keyfile: str | None = None,
    allow_insecure: bool = False,
) -> str | None:
    """Why binding to ``host`` must not happen, or None when it may.

    Anything but loopback is reachable by whoever shares the network, and the session token
    would travel in clear text (a dashboard URL carries it in the fragment, but the WebSocket
    that follows sends it in a query string). So a non-loopback bind needs TLS, or the user
    saying out loud that they know.
    """
    if host in LOOPBACK:
        return None
    if tls_certfile and tls_keyfile:
        return None
    if allow_insecure:
        return None
    return (
        f"refusing to listen on {host} without TLS: the session token would cross the network in "
        "clear text. Pass --tls-cert and --tls-key, or --insecure if you know what you are doing "
        "(a reverse proxy that terminates TLS in front of a loopback bind is the usual answer)."
    )


def bind_socket(host: str, port: int) -> socket.socket:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(128)
    sock.set_inheritable(True)
    return sock


def _display_host(host: str) -> str:
    return "127.0.0.1" if host in ("0.0.0.0", "::") else host  # noqa: S104 - display only


def dashboard_url(host: str, port: int, token: str, *, scheme: str = "http") -> str:
    # The token rides in the fragment: it is never sent to a server or written to a log.
    return f"{scheme}://{_display_host(host)}:{port}/#token={token}"


def start_plugin_pages(host: str) -> tuple[Any, int] | None:
    """Serve the dashboard pages plugins ship, on a port of their own. ``None`` when there is none.

    Its own port is what gives the page its own origin: a frame from here shares nothing with
    the dashboard, and the WebSocket handshake it would have to make is refused by the origin
    check. The socket is already listening when this returns, so a request that arrives before
    the worker loop is up waits in the backlog instead of failing.
    """
    import uvicorn

    from clite.plugins.manager import ensure_plugins_loaded
    from clite.plugins.pages import dashboard_pages, set_plugin_origin
    from clite.server.app import create_plugin_pages_app

    ensure_plugins_loaded()  # the page list is "the plugins loaded right now", so load them
    if not dashboard_pages():
        return None
    sock = bind_socket(host, 0)
    port = sock.getsockname()[1]
    app = create_plugin_pages_app(bind_host=host)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", access_log=False, lifespan="off"))
    threading.Thread(
        target=server.run, kwargs={"sockets": [sock]}, daemon=True, name="clite-plugin-pages"
    ).start()
    set_plugin_origin(f"http://{_display_host(host)}:{port}")
    return server, port


def serve(
    host: str = "127.0.0.1",
    port: int = 0,
    *,
    token: str | None = None,
    open_browser: bool = False,
    out: TextIO | None = None,
    client_factory: Callable[[], Any] | None = None,
    on_ready: Callable[[int, str, Any], None] | None = None,
    tls_certfile: str | None = None,
    tls_keyfile: str | None = None,
    allow_insecure: bool = False,
    throttle: Any = None,
) -> int:
    import uvicorn

    from clite.server.app import create_app, max_message_bytes

    out = out or sys.stdout
    refusal = bind_refusal(
        host, tls_certfile=tls_certfile, tls_keyfile=tls_keyfile, allow_insecure=allow_insecure
    )
    if refusal is not None:
        print(refusal, file=sys.stderr, flush=True)
        return 2
    inherited = os.environ.get(SESSION_TOKEN_ENV, "").strip()
    token = token or inherited or secrets.token_urlsafe(32)
    sock = bind_socket(host, port)
    bound_port = sock.getsockname()[1]

    app = create_app(
        token, client_factory=client_factory, bind_host=host, throttle=throttle
    )
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            log_level="warning",
            access_log=False,
            lifespan="off",
            # The ASGI server refuses an oversized frame before the app ever sees it, so a huge
            # message is never held in memory as a Python string.
            ws_max_size=max_message_bytes(),
            ssl_certfile=tls_certfile or None,
            ssl_keyfile=tls_keyfile or None,
        )
    )
    scheme = "https" if tls_certfile and tls_keyfile else "http"
    # Before the ready line: a client that reacts to it may ask for the pages right away.
    pages = start_plugin_pages(host)
    print(f"{BACKEND_READY_SENTINEL} port={bound_port}", file=out, flush=True)
    url = dashboard_url(host, bound_port, token, scheme=scheme)
    if not inherited:
        # Nobody handed us a token, so a person started this: show them how to get in.
        print(f"Dashboard: {url}", file=sys.stderr, flush=True)
    if host not in LOOPBACK:
        print(
            f"WARNING: listening on {host}. Anyone who can reach this port and has the token controls the agent.",
            file=sys.stderr,
            flush=True,
        )
    if open_browser:
        threading.Timer(0.5, webbrowser.open, args=(url,)).start()
    if on_ready is not None:
        on_ready(bound_port, token, server)
    try:
        server.run(sockets=[sock])
    finally:
        if pages is not None:
            pages[0].should_exit = True
        sock.close()
    return 0
