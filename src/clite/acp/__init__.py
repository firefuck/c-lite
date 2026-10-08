"""Agent Client Protocol server: lets an editor (Zed and others) drive the agent over stdio.

``clite acp`` runs it; ``python -m clite.acp.entry`` does the same thing. The protocol is an
external one (JSON-RPC 2.0, newline-delimited on stdout) and what this agent implements of it
is written down in ``docs/spesifikasi/acp.md``. The layer sits on ``clite.runtime`` like every
other surface — ``acp/server.py`` is the wire, ``acp/session.py`` the translation layer, and
neither holds conversation logic.
"""
