"""Small commands: version, status, doctor, logs, memory, acp."""

from __future__ import annotations

import argparse
import platform
import shutil
import sqlite3
import sys
import time

from clite import __version__
from clite.core.brand import DISPLAY_NAME
from clite.core.config import get_path, load_config
from clite.core.constants import display_home, get_home, get_logs_dir
from clite.core.errors import CliteError, ConfigError
from clite.core.profiles import get_active_profile_name


def run_version(args: argparse.Namespace) -> int:
    print(f"{DISPLAY_NAME} {__version__}")
    print(f"Python {platform.python_version()} on {platform.system()} {platform.machine()}")
    print(f"Home: {display_home()} (profile: {get_active_profile_name()})")
    return 0


def run_status(args: argparse.Namespace) -> int:
    from clite.cron.jobs import get_job_store
    from clite.plugins.manager import ensure_plugins_loaded
    from clite.providers.runtime import resolve_runtime_provider
    from clite.state.db import get_session_db

    config = load_config()
    print(f"Profile:   {get_active_profile_name()} ({display_home()})")
    try:
        route = resolve_runtime_provider(config=config)
        print(f"Model:     {route.model} via {route.provider}")
    except CliteError as exc:
        print(f"Model:     not configured ({exc})")
    print(f"Toolsets:  {', '.join(config.get('toolsets') or [])}")
    plugins = [info.name for info in ensure_plugins_loaded().list() if info.status == "loaded"]
    print(f"Plugins:   {', '.join(plugins) or 'none loaded'}")
    platforms = [name for name, settings in (get_path(config, 'gateway.platforms', {}) or {}).items()
                 if isinstance(settings, dict) and settings.get("enabled", True)]
    print(f"Gateway:   {', '.join(platforms) or 'no platform configured'}")
    jobs = get_job_store().list()
    print(f"Cron:      {sum(1 for job in jobs if job.get('enabled', True))} active job(s)")
    print(f"Sessions:  {len(get_session_db().list_sessions(limit=10_000))} stored")
    return 0


def run_doctor(args: argparse.Namespace) -> int:
    """Check the installation. Exit code 1 when something that blocks normal use is wrong."""
    problems = 0

    def check(label: str, ok: bool, detail: str = "", *, required: bool = True) -> None:
        nonlocal problems
        mark = "ok  " if ok else ("FAIL" if required else "warn")
        print(f"[{mark}] {label}" + (f": {detail}" if detail else ""))
        if not ok and required:
            problems += 1

    check("Python 3.11 or newer", sys.version_info >= (3, 11), platform.python_version())
    home = get_home()
    try:
        home.mkdir(parents=True, exist_ok=True)
        probe = home / ".doctor-probe"
        probe.write_text("ok")
        probe.unlink()
        check("Home directory is writable", True, display_home())
    except OSError as exc:
        check("Home directory is writable", False, str(exc))

    try:
        config = load_config()
        check("config.yaml is valid", True)
    except ConfigError as exc:
        config = {}
        check("config.yaml is valid", False, str(exc))

    try:
        connection = sqlite3.connect(":memory:")
        connection.execute("CREATE VIRTUAL TABLE probe USING fts5(text)")
        connection.close()
        check("SQLite full-text search (FTS5)", True)
    except sqlite3.OperationalError:
        check("SQLite full-text search (FTS5)", False, "session search falls back to slower LIKE matching", required=False)

    from clite.providers.runtime import resolve_runtime_provider

    try:
        route = resolve_runtime_provider(config=config)
        check("Model provider is configured", True, f"{route.model} via {route.provider}")
        if args.online and route.profile is not None:
            from clite.providers.models import fetch_models

            models = fetch_models(route.profile, api_key=route.api_key, base_url=route.base_url)
            check("Provider answers", models is not None, f"{len(models or [])} models listed" if models else "the model list could not be fetched")
    except CliteError as exc:
        check("Model provider is configured", False, str(exc))

    from clite.tools.environments import environment_backends

    backend = str(get_path(config, "terminal.backend", "local"))
    check("Terminal backend exists", backend in environment_backends(), backend)

    from clite.plugins.manager import ensure_plugins_loaded

    try:
        manager = ensure_plugins_loaded()
        broken = [f"{info.name} ({info.error})" for info in manager.list() if info.status == "error"]
        check("Enabled plugins load", not broken, "; ".join(broken))
        pending = len(manager.pending_shell_hooks)
        check("Shell hooks are approved", not pending,
              f"{pending} configured hook(s) will not run until you approve them: clite hooks approve", required=False)
    except CliteError as exc:  # plugins are gated by config; with a broken config they cannot be checked
        check("Enabled plugins load", False, f"not checked: {exc}", required=False)

    node = shutil.which("node")
    check("Node.js for the TUI and desktop app", node is not None,
          node or "not found; the classic CLI and the dashboard work without it", required=False)
    print("\nEverything needed is in place." if not problems else f"\n{problems} problem(s) need attention.")
    return 1 if problems else 0


def run_logs(args: argparse.Namespace) -> int:
    path = get_logs_dir() / ("errors.log" if args.errors else "agent.log")
    if not path.is_file():
        print(f"No log yet at {path}")
        return 0
    with open(path, encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
        sys.stdout.writelines(lines[-args.lines:])
        if args.follow:
            try:
                while True:
                    line = handle.readline()
                    if line:
                        sys.stdout.write(line)
                        sys.stdout.flush()
                    else:
                        time.sleep(0.5)
            except KeyboardInterrupt:
                pass
    return 0


def run_memory(args: argparse.Namespace) -> int:
    from clite.agent.memory import MemoryStore

    config = load_config()
    store = MemoryStore(int(get_path(config, "memory.memory_char_limit", 2200)), int(get_path(config, "memory.user_char_limit", 1375)))
    for target, label in (("memory", "MEMORY.md (agent notes)"), ("user", "USER.md (user profile)")):
        entries = store.entries(target)
        print(f"{label}: {len(entries)} entries")
        for entry in entries:
            print(f"  - {entry}")
    return 0


def run_acp(args: argparse.Namespace) -> int:
    print("The ACP (editor integration) server is not implemented yet. See docs/roadmap/fase-6-ekosistem.md, task F6-T4.",
          file=sys.stderr)
    return 2


def register(subparsers: argparse._SubParsersAction) -> None:
    subparsers.add_parser("version", help="print version information").set_defaults(handler=run_version)
    subparsers.add_parser("status", help="show what is configured").set_defaults(handler=run_status)
    doctor = subparsers.add_parser("doctor", help="check the installation")
    doctor.add_argument("--online", action="store_true", help="also call the provider's API")
    doctor.set_defaults(handler=run_doctor)
    logs = subparsers.add_parser("logs", help="show the agent log")
    logs.add_argument("-n", "--lines", type=int, default=50)
    logs.add_argument("--errors", action="store_true", help="show errors.log instead")
    logs.add_argument("-f", "--follow", action="store_true")
    logs.set_defaults(handler=run_logs)
    subparsers.add_parser("memory", help="show persistent memory").set_defaults(handler=run_memory)
    subparsers.add_parser("acp", help="editor integration server (not implemented yet)").set_defaults(handler=run_acp)
