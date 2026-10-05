"""Runtime: what every surface shares on top of the agent.

``build_agent`` (wiring), ``ChatSession`` (one conversation as a surface sees it) and the
slash command registry with its handlers. A surface imports from here and never from another
surface.
"""

from clite.runtime.factory import build_agent
from clite.runtime.session import ChatSession, SlashResult

__all__ = ["ChatSession", "SlashResult", "build_agent"]
