"""Contract registries: every JSON-RPC method, event and server request is declared once.

The declarations are Pydantic models. They validate requests at the boundary, and
``scripts/gen_rpc_contracts.py`` turns them into TypeScript types for the Node and browser
clients, so the two sides cannot drift apart silently.

Rules:

* ``Params`` forbids unknown fields. A client sending a field the server does not know is a
  bug on one side or the other, and it should be loud.
* Adding an optional field is backwards compatible. Removing or renaming one is not: add a
  new method instead and keep the old one until every client has moved.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

PROTOCOL_VERSION = 1


class Params(BaseModel):
    """Request parameters. Unknown fields are rejected."""

    model_config = ConfigDict(extra="forbid")


class Result(BaseModel):
    """A method's result."""

    model_config = ConfigDict(extra="forbid")


class Payload(BaseModel):
    """The payload of an event."""

    model_config = ConfigDict(extra="forbid")


class Empty(Params):
    pass


class Ok(Result):
    ok: bool = True


@dataclass(frozen=True)
class MethodSpec:
    name: str
    params: type[BaseModel]
    result: type[BaseModel]
    description: str = ""


@dataclass(frozen=True)
class ServerRequestSpec:
    name: str
    params: type[BaseModel]
    result: type[BaseModel]
    description: str = ""


METHODS: dict[str, MethodSpec] = {}
EVENTS: dict[str, type[BaseModel]] = {}
SERVER_REQUESTS: dict[str, ServerRequestSpec] = {}


def method(name: str, params: type[BaseModel], result: type[BaseModel], description: str = "") -> MethodSpec:
    if name in METHODS:
        raise ValueError(f"RPC method {name!r} is declared twice")
    spec = METHODS[name] = MethodSpec(name, params, result, description)
    return spec


def event(event_type: str, payload: type[BaseModel]) -> type[BaseModel]:
    if event_type in EVENTS:
        raise ValueError(f"RPC event {event_type!r} is declared twice")
    EVENTS[event_type] = payload
    return payload


def server_request(name: str, params: type[BaseModel], result: type[BaseModel], description: str = "") -> ServerRequestSpec:
    if name in SERVER_REQUESTS:
        raise ValueError(f"server request {name!r} is declared twice")
    spec = SERVER_REQUESTS[name] = ServerRequestSpec(name, params, result, description)
    return spec


JsonObject = dict[str, Any]
