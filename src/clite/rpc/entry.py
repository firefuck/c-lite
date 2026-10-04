"""Stdio entry point: ``python -m clite.rpc.entry``.

The TUI (and any other local front-end) spawns this process and speaks JSON-RPC over its
stdin and stdout, one JSON document per line.

Stdout is the wire. Nothing but protocol messages may be written to it, so ``sys.stdout`` is
pointed at stderr for the life of the process: a stray ``print`` in a tool or a plugin then
lands in the log instead of corrupting the stream.
"""

from __future__ import annotations

import os
import sys

from clite.core.brand import ENV_PREFIX
from clite.core.config import config_get
from clite.core.env import load_env
from clite.core.logging import setup_logging
from clite.core.profiles import apply_profile_override
from clite.rpc.server import RpcServer
from clite.rpc.transport import StdioTransport


def serve_stdio(stdin=None, stdout=None, *, platform: str | None = None) -> int:
    wire = stdout or sys.stdout
    sys.stdout = sys.stderr
    source = stdin or sys.stdin
    server = RpcServer(StdioTransport(wire), platform=platform or os.environ.get(f"{ENV_PREFIX}_RPC_PLATFORM", "tui"))
    server.announce()
    try:
        for line in source:
            server.handle_line(line)
    except KeyboardInterrupt:
        pass
    finally:
        server.wait_idle(timeout=2.0)
        server.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    apply_profile_override(list(sys.argv[1:] if argv is None else argv))
    load_env()
    setup_logging(str(config_get("logging.level", "INFO")), max_size_mb=int(config_get("logging.max_size_mb", 5)),
                  backup_count=int(config_get("logging.backup_count", 3)))
    return serve_stdio()


if __name__ == "__main__":
    raise SystemExit(main())
