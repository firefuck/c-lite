"""RPC handlers for the agent's memory, read and edited through the store the memory tool uses."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from clite.core.config import get_path, load_config
from clite.rpc.contracts import schema
from clite.rpc.contracts.base import Empty
from clite.rpc.server import RpcServer, rpc_method

if TYPE_CHECKING:
    from clite.agent.memory import MemoryStore


def _memory_store() -> MemoryStore:
    """The same store the `memory` tool writes through, with its limits and guards."""
    from clite.agent.memory import MemoryStore

    config = load_config()
    return MemoryStore(
        int(get_path(config, "memory.memory_char_limit", 2200)),
        int(get_path(config, "memory.user_char_limit", 1375)),
    )


def _memory_result(store: MemoryStore, result: dict[str, Any]) -> schema.MemoryEditResult:
    config = load_config()
    return schema.MemoryEditResult(
        success=bool(result.get("success")),
        message=str(result.get("message") or result.get("error") or ""),
        memory=store.entries("memory"),
        user=store.entries("user"),
        memory_limit=store.limits["memory"],
        user_limit=store.limits["user"],
        provider=str(get_path(config, "memory.provider", "") or ""),
    )


@rpc_method("memory.get")
def memory_get(server: RpcServer, params: Empty) -> schema.MemoryGetResult:
    store = _memory_store()
    return schema.MemoryGetResult(
        memory=store.entries("memory"),
        user=store.entries("user"),
        memory_limit=store.limits["memory"],
        user_limit=store.limits["user"],
        provider=str(get_path(load_config(), "memory.provider", "") or ""),
    )


@rpc_method("memory.set")
def memory_set(server: RpcServer, params: schema.MemoryEditParams) -> schema.MemoryEditResult:
    store = _memory_store()
    if params.action == "add":
        result = store.add(params.target, params.content)
    elif params.action == "replace":
        result = store.replace(params.target, params.old_text, params.content)
    else:
        result = store.remove(params.target, params.old_text)
    return _memory_result(store, result)
