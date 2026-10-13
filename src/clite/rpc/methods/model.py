"""RPC handlers for providers and models: listing them, switching the model, first-run setup."""

from __future__ import annotations

from clite.core.config import get_path, load_config
from clite.core.errors import CliteError
from clite.providers.models import list_models
from clite.providers.registry import list_providers
from clite.providers.runtime import resolve_runtime_provider
from clite.rpc.contracts import schema
from clite.rpc.contracts.base import Empty
from clite.rpc.server import RpcServer, rpc_method


@rpc_method("model.list")
def model_list(server: RpcServer, params: schema.ModelListParams) -> schema.ModelListResult:
    current = ""
    provider = params.provider
    try:
        route = resolve_runtime_provider()
        current = route.model if not provider or provider == route.provider else ""
        provider = provider or route.provider
    except CliteError:
        if not provider:
            raise
    models = list_models(provider, refresh=params.refresh)
    return schema.ModelListResult(
        provider=provider,
        current=current,
        models=[schema.ModelEntry(id=m.id, context_length=m.context_length) for m in models],
    )


@rpc_method("model.set")
def model_set(server: RpcServer, params: schema.ModelSetParams) -> schema.ModelSetResult:
    session = server.get_session(params.session_id)
    result = session.chat.switch_model(params.model, persist=params.persist)
    if result.success:
        server.emit("session.info", session.id, session.info())
    route = result.route
    return schema.ModelSetResult(
        success=result.success,
        message=result.message,
        model=route.model if route else "",
        provider=route.provider if route else "",
    )


@rpc_method("providers.list")
def providers_list(server: RpcServer, params: Empty) -> schema.ProvidersResult:
    config = load_config()
    return schema.ProvidersResult(
        current=str(get_path(config, "model.provider", "") or ""),
        providers=[
            schema.ProviderEntry(
                name=p.name,
                display_name=p.display_name,
                description=p.description,
                configured=p.is_configured(),
                env_vars=list(p.env_vars),
                needs_base_url=not p.base_url and p.api_mode != "mock",
                signup_url=p.signup_url,
            )
            for p in list_providers(config)
        ],
    )


@rpc_method("setup.apply")
def setup_apply(server: RpcServer, params: schema.SetupApplyParams) -> schema.SetupApplyResult:
    from clite.runtime.setup import apply_setup

    result = apply_setup(
        params.provider, api_key=params.api_key, model=params.model, base_url=params.base_url
    )
    return schema.SetupApplyResult(provider=result["provider"], model=result["model"])
