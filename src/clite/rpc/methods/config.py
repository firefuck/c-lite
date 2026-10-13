"""RPC handlers for settings: the configuration keys and the credentials in the profile's ``.env``."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import Any

from clite.core.config import config_set, get_path, load_config_unexpanded
from clite.core.config_defaults import DEFAULT_CONFIG, is_sensitive_config_key
from clite.core.env import secret_names
from clite.rpc.contracts import schema
from clite.rpc.contracts.base import Empty, Ok
from clite.rpc.server import REQUEST_FAILED, RpcError, RpcServer, rpc_method


def _flatten_config(node: Mapping[str, Any], prefix: str = "") -> Iterator[tuple[str, Any]]:
    for key, value in node.items():
        dotted = f"{prefix}{key}"
        if isinstance(value, Mapping):
            yield from _flatten_config(value, dotted + ".")
        else:
            yield dotted, value


@rpc_method("config.get")
def config_get_method(server: RpcServer, params: schema.ConfigGetParams) -> schema.ConfigGetResult:
    # Unexpanded: a setting written as ${OPENAI_API_KEY} reads back as that text, never as the
    # secret. The dashboard shows this; the runtime reads the expanded form elsewhere.
    config = load_config_unexpanded()
    return schema.ConfigGetResult(value=config if not params.key else get_path(config, params.key))


@rpc_method("config.list")
def config_list_method(server: RpcServer, params: Empty) -> schema.ConfigListResult:
    effective = load_config_unexpanded()
    entries = [
        schema.ConfigEntry(
            key=key,
            value=get_path(effective, key),
            default=default,
            group=key.split(".", 1)[0],
            sensitive=is_sensitive_config_key(key),
        )
        for key, default in _flatten_config(DEFAULT_CONFIG)
    ]
    return schema.ConfigListResult(entries=entries)


@rpc_method("config.set")
def config_set_method(server: RpcServer, params: schema.ConfigSetParams) -> Ok:
    if not params.key or params.key.startswith("_"):
        raise RpcError(REQUEST_FAILED, "invalid config key")
    if is_sensitive_config_key(params.key) and not params.confirm:
        raise RpcError(
            REQUEST_FAILED,
            f"{params.key} changes what the agent may do without asking; send confirm=true to write it",
        )
    config_set(params.key, params.value)
    return Ok()


def _credentials() -> schema.CredentialsListResult:
    from clite.core.env import secret_source

    entries = []
    for name in sorted(secret_names()):
        source = secret_source(name)
        entries.append(schema.CredentialEntry(name=name, filled=bool(source), source=source))
    return schema.CredentialsListResult(credentials=entries)


@rpc_method("credentials.list")
def credentials_list(server: RpcServer, params: Empty) -> schema.CredentialsListResult:
    return _credentials()


@rpc_method("credentials.set")
def credentials_set(server: RpcServer, params: schema.CredentialSetParams) -> schema.CredentialsListResult:
    from clite.core.env import save_secret

    name = params.name.strip().upper()
    if not name:
        raise RpcError(REQUEST_FAILED, "a credential needs a name")
    if name not in secret_names():
        raise RpcError(REQUEST_FAILED, f"unknown credential {params.name!r}")
    if not params.value:
        raise RpcError(REQUEST_FAILED, "an empty value would store nothing; delete it instead")
    try:
        save_secret(name, params.value)
    except ValueError as exc:
        raise RpcError(REQUEST_FAILED, str(exc)) from exc
    return _credentials()


@rpc_method("credentials.delete")
def credentials_delete(
    server: RpcServer, params: schema.CredentialNameParams
) -> schema.CredentialsListResult:
    from clite.core.env import remove_secret

    name = params.name.strip()
    if not remove_secret(name):
        raise RpcError(REQUEST_FAILED, f"no stored credential named {name!r}")
    return _credentials()
