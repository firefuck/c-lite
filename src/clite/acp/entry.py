"""Stdio entry point: ``python -m clite.acp.entry`` and ``clite acp``.

The editor spawns this process and speaks ACP over its stdin and stdout, one JSON document
per line. Stdout is the wire, so ``sys.stdout`` is pointed at stderr for the life of the
process: a stray ``print`` in a tool, a plugin or a dependency lands in the log instead of
corrupting the protocol stream.
"""

from __future__ import annotations

import sys
from typing import TextIO

from clite.acp.server import AcpServer
from clite.core.config import config_get
from clite.core.env import load_env
from clite.core.logging import setup_logging
from clite.core.profiles import apply_profile_override
from clite.rpc.transport import StdioTransport


def serve_stdio(stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
    """Answer lines from ``stdin`` on ``stdout`` until it closes.

    ``sys.stdout`` is moved to stderr for the life of the server, so anything that prints —
    a tool, a plugin, a dependency — goes to the log instead of between two protocol messages.
    """
    wire = stdout or sys.stdout
    saved_stdout, sys.stdout = sys.stdout, sys.stderr
    source = stdin or sys.stdin
    server = AcpServer(StdioTransport(wire))
    try:
        for line in source:
            server.handle_line(line)
    except KeyboardInterrupt:
        pass
    finally:
        server.wait_idle(timeout=2.0)
        server.close()
        sys.stdout = saved_stdout
    return 0


def main(argv: list[str] | None = None) -> int:
    apply_profile_override(list(sys.argv[1:] if argv is None else argv))
    load_env()
    setup_logging(
        str(config_get("logging.level", "INFO")),
        max_size_mb=int(config_get("logging.max_size_mb", 5)),
        backup_count=int(config_get("logging.backup_count", 3)),
    )
    return serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
