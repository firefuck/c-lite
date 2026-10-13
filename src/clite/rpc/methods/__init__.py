"""RPC method handlers: importing this package registers every one of them.

Each handler is bound to its contract with ``@rpc_method`` in the module of its domain, which
the prefix of the method's name decides:

* ``system``      ``ping``, ``system.*``, ``profiles.*``, ``logs.*``
* ``session``     ``session.*``
* ``prompt``      ``prompt.*``, ``slash.*``, ``commands.*``, ``complete.*``, ``attachment.*``
* ``config``      ``config.*``, ``credentials.*``
* ``model``       ``model.*``, ``providers.*``, ``setup.*``
* ``extensions``  ``tools.*``, ``skills.*``, ``plugins.*``, ``hooks.*``, ``mcp.*``
* ``memory``      ``memory.*``
* ``cron``        ``cron.*``

A handler takes the server and the validated params, and returns the result model (or a dict
that validates against it). Handlers hold no state: sessions live on the server, everything
else in config and the session database. A new domain gets a module of its own, imported here:
a handler in a module that nothing imports is never registered.
"""

from __future__ import annotations

from clite.rpc.methods import (  # noqa: F401 - importing a domain module registers its handlers
    config,
    cron,
    extensions,
    memory,
    model,
    prompt,
    session,
    system,
)
