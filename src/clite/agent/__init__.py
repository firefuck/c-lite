"""The agent: one conversation loop shared by every surface.

``AIAgent`` is the only class surfaces construct. It is a thin facade; the turn itself runs as
a sequence of phases in ``clite.agent.turn``, each a plain function over a ``TurnState``.
"""

from clite.agent.agent import AIAgent
from clite.agent.callbacks import AgentCallbacks
from clite.agent.state import TurnResult

__all__ = ["AIAgent", "AgentCallbacks", "TurnResult"]
