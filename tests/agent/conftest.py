"""Fixtures for agent tests: an agent wired to a scripted model."""

from __future__ import annotations

import pytest

from clite.agent import AIAgent
from clite.providers.testing import ScriptedClient, mock_route
from clite.tools.registry import registry, tool_result


@pytest.fixture
def make_agent(clite_home, tmp_path):
    """``make_agent(responses, **agent_kwargs) -> (agent, client)``.

    The agent runs in an empty workspace with only the ``file`` toolset unless told
    otherwise, against a ``ScriptedClient`` holding ``responses``.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    created: list[AIAgent] = []

    def factory(responses=None, **kwargs):
        client = kwargs.pop("client", None) or ScriptedClient(list(responses or []))
        kwargs.setdefault("enabled_toolsets", ["file"])
        kwargs.setdefault("cwd", str(workspace))
        kwargs.setdefault("skip_context_files", True)
        route = kwargs.pop("route", None) or mock_route()
        agent = AIAgent(route, client=client, **kwargs)
        created.append(agent)
        return agent, client

    yield factory
    for agent in created:
        agent.close()


@pytest.fixture
def probe_tools():
    """Three test tools in toolset ``probe`` that record how they were called.

    ``probe_read`` is parallel-safe, ``probe_write`` is path-scoped, ``probe_act`` is
    sequential-only. ``calls`` lists ``(tool, args)`` in the order handlers started.
    """
    calls: list[tuple[str, dict]] = []

    def handler(name):
        def run(args, ctx=None):
            calls.append((name, dict(args)))
            hook = args.get("_hook")
            return tool_result(tool=name, echo={k: v for k, v in args.items() if k != "_hook"}, hook=hook)

        return run

    schema = {"description": "probe", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}}
    registry.register("probe_read", "probe", dict(schema), handler("probe_read"), origin="test", parallel="safe")
    registry.register("probe_write", "probe", dict(schema), handler("probe_write"), origin="test", parallel="path",
                      path_args=("path",))
    registry.register("probe_act", "probe", dict(schema), handler("probe_act"), origin="test")
    return calls
