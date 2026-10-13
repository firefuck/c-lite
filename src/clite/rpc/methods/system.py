"""RPC handlers that describe the running backend: its version, setup, profiles and logs."""

from __future__ import annotations

from clite import __version__
from clite.core.config import get_path, load_config
from clite.core.constants import display_home
from clite.core.errors import CliteError
from clite.core.profiles import get_active_profile_name
from clite.providers.runtime import resolve_runtime_provider
from clite.rpc.contracts import schema
from clite.rpc.contracts.base import PROTOCOL_VERSION, Empty
from clite.rpc.server import RpcServer, rpc_method


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
        notifications=bool(get_path(load_config(), "dashboard.notifications", True)),
    )


@rpc_method("profiles.list")
def profiles_list(server: RpcServer, params: Empty) -> schema.ProfilesListResult:
    from clite.core.profiles import get_sticky_profile, list_profiles

    return schema.ProfilesListResult(
        current=get_active_profile_name(),
        sticky=get_sticky_profile(),
        profiles=[schema.ProfileEntry(name=p.name, active=p.active) for p in list_profiles()],
    )


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
