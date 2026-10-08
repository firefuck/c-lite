"""RPC method handlers. Each is bound to its contract with ``@rpc_method``.

A handler takes the server and the validated params, and returns the result model (or a dict
that validates against it). Handlers hold no state: sessions live on the server, everything
else in config and the session database.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from clite import __version__
from clite.agent.attachments import AttachmentError
from clite.core.config import config_set, get_path, load_config, load_config_unexpanded
from clite.core.config_defaults import DEFAULT_CONFIG, is_sensitive_config_key
from clite.core.constants import display_home
from clite.core.env import secret_names
from clite.core.errors import CliteError
from clite.core.profiles import get_active_profile_name
from clite.plugins.manager import get_plugin_manager, set_plugin_enabled
from clite.providers.models import list_models
from clite.providers.registry import list_providers
from clite.providers.runtime import resolve_runtime_provider
from clite.rpc.contracts import schema
from clite.rpc.contracts.base import PROTOCOL_VERSION, Empty, Ok
from clite.rpc.server import REQUEST_FAILED, RpcError, RpcServer, rpc_method
from clite.rpc.session import RpcSession
from clite.runtime.commands import command_catalog
from clite.runtime.trajectory import build_trajectory
from clite.skills.catalog import discover_skills, get_skill, linked_files, read_skill_file
from clite.state.db import get_session_db
from clite.tools.registry import discover_builtin_tools
from clite.tools.toolsets import all_toolsets, resolve_toolset

# ── system ───────────────────────────────────────────────────────────────────────────────


@rpc_method("ping")
def ping(server: RpcServer, params: Empty) -> schema.PingResult:
    return schema.PingResult(version=__version__)


@rpc_method("system.info")
def system_info(server: RpcServer, params: Empty) -> schema.SystemInfoResult:
    model = provider = ""
    try:
        route = resolve_runtime_provider()
        model, provider, configured = route.model, route.provider, True
    except CliteError:
        configured = False
    return schema.SystemInfoResult(
        version=__version__,
        protocol_version=PROTOCOL_VERSION,
        home=display_home(),
        profile=get_active_profile_name(),
        configured=configured,
        model=model,
        provider=provider,
    )


# ── sessions ─────────────────────────────────────────────────────────────────────────────


@rpc_method("session.create")
def session_create(server: RpcServer, params: schema.SessionCreateParams) -> schema.SessionInfo:
    session = RpcSession(server, params)
    session.id = server.add_session(session)
    return session.info()


@rpc_method("session.info")
def session_info(server: RpcServer, params: schema.SessionRef) -> schema.SessionInfo:
    return server.get_session(params.session_id).info()


@rpc_method("session.list")
def session_list(server: RpcServer, params: schema.SessionListParams) -> schema.SessionListResult:
    rows = get_session_db().list_sessions(
        limit=max(1, min(params.limit, 200)),
        sources=[params.source] if params.source else None,
        include_archived=params.include_archived,
    )
    return schema.SessionListResult(
        sessions=[
            schema.StoredSession(
                id=row["id"],
                title=row.get("title") or "",
                source=row["source"],
                model=row.get("model") or "",
                message_count=row.get("message_count") or 0,
                started_at=row["started_at"],
                last_activity_at=row.get("last_activity_at"),
                archived=bool(row.get("archived")),
                pinned=bool(row.get("pinned")),
            )
            for row in rows
        ]
    )


@rpc_method("session.history")
def session_history(server: RpcServer, params: schema.SessionRef) -> schema.SessionHistoryResult:
    return schema.SessionHistoryResult(messages=server.get_session(params.session_id).history())


@rpc_method("session.close")
def session_close(server: RpcServer, params: schema.SessionRef) -> Ok:
    server.get_session(params.session_id)
    server.remove_session(params.session_id)
    return Ok()


@rpc_method("session.interrupt")
def session_interrupt(server: RpcServer, params: schema.SessionRef) -> Ok:
    server.get_session(params.session_id).chat.interrupt()
    return Ok()


@rpc_method("session.steer")
def session_steer(server: RpcServer, params: schema.SessionSteerParams) -> Ok:
    server.get_session(params.session_id).chat.steer(params.text)
    return Ok()


@rpc_method("session.title")
def session_title(server: RpcServer, params: schema.SessionTitleParams) -> schema.SessionTitleResult:
    session = server.get_session(params.session_id)
    if params.title is not None:
        title = session.chat.set_title(params.title)
        server.emit("session.info", session.id, session.info())
        return schema.SessionTitleResult(title=title)
    return schema.SessionTitleResult(title=session.info().title)


@rpc_method("session.delete")
def session_delete(server: RpcServer, params: schema.SessionDeleteParams) -> Ok:
    if any(session.chat.session_id == params.stored_session_id for session in server.sessions.values()):
        raise RpcError(REQUEST_FAILED, "that session is open; close it or start a new one first")
    if not get_session_db().delete_session(params.stored_session_id):
        raise RpcError(REQUEST_FAILED, f"no stored session {params.stored_session_id!r}")
    return Ok()


@rpc_method("session.rename")
def session_rename(server: RpcServer, params: schema.SessionRenameParams) -> schema.SessionRenameResult:
    _require_stored_session(params.stored_session_id)
    title = get_session_db().set_title(params.stored_session_id, params.title)
    # If that session is open, its runtime copy carries the old title: refresh it too.
    for session in list(server.sessions.values()):
        if session.chat.session_id == params.stored_session_id:
            session.chat.set_title(title)
            server.emit("session.info", session.id, session.info())
            break
    return schema.SessionRenameResult(title=title)


@rpc_method("session.search")
def session_search(server: RpcServer, params: schema.SessionSearchParams) -> schema.SessionSearchResult:
    hits = get_session_db().search_messages(params.query, limit=max(1, min(params.limit, 200)))
    return schema.SessionSearchResult(
        hits=[
            schema.SessionSearchHit(
                stored_session_id=hit["session_id"],
                title=hit.get("session_title") or "",
                source=hit.get("session_source") or "",
                role=hit.get("role") or "",
                snippet=hit.get("snippet") or "",
                timestamp=hit.get("timestamp"),
            )
            for hit in hits
        ]
    )


def _require_stored_session(stored_session_id: str) -> dict[str, Any]:
    row = get_session_db().get_session(stored_session_id)
    if row is None:
        raise RpcError(REQUEST_FAILED, f"no stored session {stored_session_id!r}")
    return row


@rpc_method("session.pin")
def session_pin(server: RpcServer, params: schema.SessionPinParams) -> Ok:
    _require_stored_session(params.stored_session_id)
    get_session_db().update_session(params.stored_session_id, pinned=1 if params.pinned else 0)
    return Ok()


@rpc_method("session.archive")
def session_archive(server: RpcServer, params: schema.SessionArchiveParams) -> Ok:
    _require_stored_session(params.stored_session_id)
    get_session_db().update_session(params.stored_session_id, archived=1 if params.archived else 0)
    return Ok()


@rpc_method("session.export")
def session_export(server: RpcServer, params: schema.SessionExportParams) -> schema.SessionExportResult:
    row = _require_stored_session(params.stored_session_id)
    db = get_session_db()
    if params.format == "trajectory":
        document = build_trajectory(row, db.get_messages(row["id"]))
        count = len(document["steps"])
    else:
        messages = [
            {key: value for key, value in message.items() if key != "_row_id"}
            for message in db.get_messages(row["id"])
        ]
        document = {
            "session": {
                key: row[key] for key in ("id", "source", "model", "provider", "title", "started_at")
            },
            "messages": messages,
        }
        count = len(messages)
    return schema.SessionExportResult(
        filename=f"{row['id']}.json",
        content=json.dumps(document, ensure_ascii=False, indent=2),
        count=count,
    )


@rpc_method("session.compress")
def session_compress(server: RpcServer, params: schema.SessionCompressParams) -> schema.SessionCompressResult:
    session = server.get_session(params.session_id)
    if session.busy:
        from clite.rpc.server import SESSION_BUSY

        raise RpcError(SESSION_BUSY, "a turn is running")
    compressed = session.chat.agent.compress_context(focus=params.focus)
    server.emit("session.info", session.id, session.info())
    return schema.SessionCompressResult(compressed=compressed, message_count=len(session.chat.agent.messages))


@rpc_method("session.usage")
def session_usage(server: RpcServer, params: schema.SessionRef) -> schema.SessionUsageResult:
    agent = server.get_session(params.session_id).chat.agent
    usage = agent.total_usage
    return schema.SessionUsageResult(
        usage=schema.UsageTotals(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            prompt_tokens=usage.prompt_tokens,
        ),
        context=schema.ContextStatus(**agent.context_status()),
    )


# ── prompts and commands ─────────────────────────────────────────────────────────────────


@rpc_method("prompt.submit")
def prompt_submit(server: RpcServer, params: schema.PromptSubmitParams) -> schema.PromptSubmitResult:
    if not params.text.strip() and not params.attachments:
        raise RpcError(REQUEST_FAILED, "the prompt is empty")
    try:
        return server.get_session(params.session_id).submit(params.text, params.busy_mode, params.attachments)
    except AttachmentError as exc:
        raise RpcError(REQUEST_FAILED, str(exc)) from exc


@rpc_method("slash.exec")
def slash_exec(server: RpcServer, params: schema.SlashExecParams) -> schema.SlashExecResult:
    return server.get_session(params.session_id).run_slash(params.command)


def _catalog(server: RpcServer, session_id: str | None) -> list[schema.CommandEntry]:
    cwd, platform = None, server.platform
    if session_id:
        session = server.get_session(session_id)
        cwd, platform = session.chat.agent.cwd, session.chat.platform
    return [schema.CommandEntry(**entry) for entry in command_catalog(platform, cwd=cwd)]


@rpc_method("commands.catalog")
def commands_catalog(server: RpcServer, params: schema.CatalogParams) -> schema.CatalogResult:
    return schema.CatalogResult(commands=_catalog(server, params.session_id))


@rpc_method("complete.slash")
def complete_slash(server: RpcServer, params: schema.CompleteParams) -> schema.CompleteResult:
    prefix = params.prefix.lstrip("/").lower()
    matches = [
        entry
        for entry in _catalog(server, params.session_id)
        if entry.name.startswith(prefix) or any(alias.startswith(prefix) for alias in entry.aliases)
    ]
    return schema.CompleteResult(items=matches[:50])


# ── configuration, models, providers ─────────────────────────────────────────────────────


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


# ── tools, skills, plugins, memory, cron ─────────────────────────────────────────────────


@rpc_method("tools.list")
def tools_list(server: RpcServer, params: schema.CatalogParams) -> schema.ToolsListResult:
    discover_builtin_tools()
    if params.session_id:
        active = set(server.get_session(params.session_id).chat.agent.tool_names)
    else:
        from clite.tools.dispatch import resolve_enabled_tools

        active = set(resolve_enabled_tools())
    toolsets = []
    for name, spec in sorted(all_toolsets().items()):
        tools = resolve_toolset(name)
        toolsets.append(
            schema.ToolsetEntry(
                name=name,
                description=spec.get("description", ""),
                tools=tools,
                enabled_tools=[tool for tool in tools if tool in active],
            )
        )
    return schema.ToolsListResult(toolsets=toolsets)


@rpc_method("skills.list")
def skills_list(server: RpcServer, params: Empty) -> schema.SkillsListResult:
    return schema.SkillsListResult(
        skills=[schema.SkillEntry(**skill.summary()) for skill in discover_skills()]
    )


@rpc_method("skills.view")
def skills_view(server: RpcServer, params: schema.SkillViewParams) -> schema.SkillViewResult:
    skill = get_skill(params.name)
    if skill is None:
        raise RpcError(REQUEST_FAILED, f"no skill named {params.name!r}")
    try:
        content = read_skill_file(skill, params.file_path)
    except (PermissionError, FileNotFoundError) as exc:
        raise RpcError(REQUEST_FAILED, str(exc)) from exc
    return schema.SkillViewResult(name=skill.name, content=content, linked_files=linked_files(skill))


def _plugins() -> schema.PluginsListResult:
    manager = get_plugin_manager()
    manager.load_all()
    return schema.PluginsListResult(plugins=[schema.PluginEntry(**info.summary()) for info in manager.list()])


@rpc_method("plugins.list")
def plugins_list(server: RpcServer, params: Empty) -> schema.PluginsListResult:
    return _plugins()


@rpc_method("plugins.set_enabled")
def plugins_set_enabled(server: RpcServer, params: schema.PluginSetEnabledParams) -> schema.PluginsListResult:
    manager = get_plugin_manager()
    manager.discover()
    if params.name not in manager.plugins:
        raise RpcError(REQUEST_FAILED, f"no plugin named {params.name!r}")
    set_plugin_enabled(params.name, params.enabled)
    return _plugins()


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
def credentials_delete(server: RpcServer, params: schema.CredentialNameParams) -> schema.CredentialsListResult:
    from clite.core.env import remove_secret

    name = params.name.strip()
    if not remove_secret(name):
        raise RpcError(REQUEST_FAILED, f"no stored credential named {name!r}")
    return _credentials()


@rpc_method("logs.tail")
def logs_tail(server: RpcServer, params: schema.LogTailParams) -> schema.LogTailResult:
    from clite.core.constants import get_logs_dir
    from clite.core.redact import redact

    path = get_logs_dir() / ("errors.log" if params.source == "errors" else "agent.log")
    if not path.is_file():
        return schema.LogTailResult(path=str(path))
    want = max(1, min(params.lines, 2000))
    size = path.stat().st_size
    # Read only a window at the end: a log that has been running for months is still bounded.
    window = min(size, max(64_000, want * 400))
    with path.open("rb") as handle:
        handle.seek(size - window)
        text = handle.read().decode("utf-8", errors="replace")
    tail = text.splitlines()[-want:]
    if params.level != "all":
        tail = [line for line in tail if _log_level(line) == params.level.upper()]
    return schema.LogTailResult(
        path=str(path),
        lines=[redact(line) for line in tail],
        truncated=window < size or len(text.splitlines()) > want,
    )


def _log_level(line: str) -> str:
    """The level field of ``<date> <time> <LEVEL> <name>: <message>``, or "" for anything else."""
    parts = line.split(maxsplit=3)
    return parts[2].upper() if len(parts) >= 3 else ""


def _memory_store():
    """The same store the `memory` tool writes through, with its limits and guards."""
    from clite.agent.memory import MemoryStore

    config = load_config()
    return MemoryStore(
        int(get_path(config, "memory.memory_char_limit", 2200)),
        int(get_path(config, "memory.user_char_limit", 1375)),
    )


def _memory_result(store, result: dict[str, Any]) -> schema.MemoryEditResult:
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


@rpc_method("hooks.status")
def hooks_status(server: RpcServer, params: Empty) -> schema.HooksStatusResult:
    from clite.plugins.shell_hooks import allowlist_path, configured_hooks, is_approved

    hooks = [
        schema.ShellHookEntry(
            event=hook.event,
            command=hook.command,
            matcher=hook.matcher,
            timeout=hook.timeout,
            fail_closed=hook.fail_closed,
            approved=is_approved(hook),
        )
        for hook in configured_hooks()
    ]
    # Approval stays a local act (`clite hooks approve`): the dashboard only reports.
    return schema.HooksStatusResult(
        hooks=hooks,
        pending=sum(1 for hook in hooks if not hook.approved),
        allowlist_path=str(allowlist_path()),
    )


@rpc_method("mcp.status")
def mcp_status(server: RpcServer, params: Empty) -> schema.McpStatusResult:
    from clite.tools.mcp.client import mcp_servers_snapshot

    configured = get_path(load_config(), "mcp_servers", {}) or {}
    return schema.McpStatusResult(
        servers=[
            schema.McpServerEntry.model_validate(
                {key: row.get(key) for key in schema.McpServerEntry.model_fields if row.get(key) is not None}
            )
            for row in mcp_servers_snapshot()
        ],
        configured=len(configured) if isinstance(configured, Mapping) else 0,
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


@rpc_method("cron.output")
def cron_output(server: RpcServer, params: schema.CronOutputParams) -> schema.CronOutputResult:
    from clite.core.redact import redact
    from clite.cron.jobs import get_job_store

    job = get_job_store().get(params.job_id)
    if job is None:
        raise RpcError(REQUEST_FAILED, f"no job with id {params.job_id!r}")
    stored = job.get("last_output")
    path = Path(str(stored)) if stored else None
    if path is None or not path.is_file():
        return schema.CronOutputResult(job_id=params.job_id)
    limit = max(200, min(params.max_chars, 200_000))
    # A run may have written a very large report; read a bounded prefix and redact it.
    text = path.read_text(encoding="utf-8", errors="replace")
    return schema.CronOutputResult(
        job_id=params.job_id,
        content=redact(text[:limit]),
        path=str(path),
        truncated=len(text) > limit,
    )


def _job(job: dict[str, Any]) -> schema.CronJob:
    return schema.CronJob.model_validate(
        {key: job.get(key) for key in schema.CronJob.model_fields if job.get(key) is not None}
    )


@rpc_method("cron.list")
def cron_list(server: RpcServer, params: Empty) -> schema.CronListResult:
    from clite.cron.jobs import get_job_store

    return schema.CronListResult(jobs=[_job(job) for job in get_job_store().list()])


@rpc_method("cron.create")
def cron_create(server: RpcServer, params: schema.CronCreateParams) -> schema.CronJob:
    from clite.cron.jobs import JobError, get_job_store

    try:
        return _job(
            get_job_store().create(
                params.prompt, params.schedule, name=params.name, deliver=params.deliver, repeat=params.repeat
            )
        )
    except JobError as exc:
        raise RpcError(REQUEST_FAILED, str(exc)) from exc


@rpc_method("cron.action")
def cron_action(server: RpcServer, params: schema.CronActionParams) -> schema.CronListResult:
    from clite.cron.jobs import JobError, get_job_store

    store = get_job_store()
    try:
        if params.action == "remove":
            if not store.remove(params.job_id):
                raise JobError(f"no job with id {params.job_id!r}")
        else:
            {"pause": store.pause, "resume": store.resume, "run": store.trigger}[params.action](params.job_id)
    except JobError as exc:
        raise RpcError(REQUEST_FAILED, str(exc)) from exc
    return schema.CronListResult(jobs=[_job(job) for job in store.list()])
