"""One module per subcommand group. Each exposes ``register(subparsers)``.

Adding a subcommand is a new file here plus one line in ``SUBCOMMAND_MODULES``; ``main.py``
does not change.
"""

SUBCOMMAND_MODULES = (
    "chat", "setup", "model", "config", "tools", "skills", "plugins", "hooks", "sessions", "profile", "cron",
    "gateway", "serve", "tui", "misc",
)
