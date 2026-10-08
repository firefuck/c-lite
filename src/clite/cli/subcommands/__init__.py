"""One module per subcommand group. Each exposes ``register(subparsers)``.

Adding a subcommand is a new file here plus one line in ``SUBCOMMAND_MODULES``; ``main.py``
does not change.
"""

SUBCOMMAND_MODULES = (
    "auth",
    "chat",
    "setup",
    "model",
    "config",
    "tools",
    "skills",
    "plugins",
    "hooks",
    "mcp",
    "sessions",
    "batch",
    "profile",
    "cron",
    "gateway",
    "webhook",
    "serve",
    "tui",
    "completion",
    "update",
    "backup",
    "uninstall",
    "misc",
)
