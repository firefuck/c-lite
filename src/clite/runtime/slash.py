"""Slash command handlers.

Convention: the handler for ``/name`` is ``_handle_name(session, args) -> SlashResult``, and
the dispatch table at the bottom is built from the registry. A test checks that every
command in ``COMMAND_REGISTRY`` has a handler and every handler a command, so the two cannot
drift apart.

Handlers return text. They never print: the same handler serves the terminal, the desktop
app and a chat platform.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import TYPE_CHECKING

from clite.agent.messages import content_text, is_internal
from clite.agent.prompt.builder import build_prompt_tiers
from clite.core.config import config_set, get_path, load_config
from clite.core.constants import display_home, get_config_path, get_logs_dir
from clite.core.errors import CliteError
from clite.core.profiles import get_active_profile_name, list_profiles
from clite.plugins.manager import get_plugin_manager
from clite.plugins.shell_hooks import configured_hooks, is_approved
from clite.providers.models import list_models
from clite.providers.registry import list_providers
from clite.runtime.commands import COMMAND_REGISTRY, command_catalog
from clite.runtime.session import ACTION_CLIPBOARD, ACTION_NEW, ACTION_QUIT, ACTION_SUBMIT, SlashResult
from clite.skills.catalog import discover_skills
from clite.state.db import get_session_db
from clite.tools.toolsets import all_toolsets, resolve_toolset, toolset_exists

if TYPE_CHECKING:
    from clite.runtime.session import ChatSession

REASONING_LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
TOOL_PROGRESS_LEVELS = ("off", "new", "all", "verbose")


def _when(timestamp: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp)) if timestamp else ""


def _clip(text: str, width: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= width else text[: width - 1] + "…"


# ── session ──────────────────────────────────────────────────────────────────────────────


def _handle_new(session: ChatSession, args: str) -> SlashResult:
    session_id = session.new_session()
    return SlashResult("Started a new session.", ACTION_NEW, {"session_id": session_id})


def _handle_retry(session: ChatSession, args: str) -> SlashResult:
    text = session.undo()
    if text is None:
        return SlashResult("Nothing to retry.")
    return SlashResult(text, ACTION_SUBMIT)


def _handle_image(session: ChatSession, args: str) -> SlashResult:
    """Queue an image for the next message, or submit one now with a caption after the path."""
    stripped = args.strip().strip('"').strip("'")
    if not stripped:
        return SlashResult("Usage: /image <path> [prompt]. It is attached to your next message.")
    path, _, caption = stripped.partition(" ")
    try:
        queued = session.queue_image(path)
    except Exception as exc:  # noqa: BLE001 - report, never crash the surface
        return SlashResult(f"Could not attach {path!r}: {exc}")
    if caption.strip():
        # The image is already queued; submitting the caption consumes it in the same turn.
        return SlashResult(caption.strip(), ACTION_SUBMIT)
    return SlashResult(f"{queued}. Now send your message.")


def _handle_undo(session: ChatSession, args: str) -> SlashResult:
    text = session.undo()
    if text is None:
        return SlashResult("Nothing to undo.")
    return SlashResult(f"Removed the last exchange (your message was: {_clip(text, 80)})")


def _handle_history(session: ChatSession, args: str) -> SlashResult:
    count = int(args) if args.isdigit() else 20
    lines = []
    for message in [message for message in session.agent.messages if not is_internal(message)][-count:]:
        role = message.get("role", "")
        if role == "tool":
            lines.append(f"  [tool {message.get('name')}] {_clip(content_text(message.get('content')), 100)}")
            continue
        text = content_text(message.get("content"))
        calls = ", ".join(call["function"]["name"] for call in message.get("tool_calls") or [])
        if calls:
            text = f"{text} [calls: {calls}]".strip()
        lines.append(f"{role}: {_clip(text, 200)}")
    return SlashResult("\n".join(lines) or "The conversation is empty.")


def _handle_title(session: ChatSession, args: str) -> SlashResult:
    if not args:
        title = (get_session_db().get_session(session.session_id) or {}).get("title")
        return SlashResult(
            f"Title: {title}" if title else "This session has no title yet. Set one with /title <text>."
        )
    return SlashResult(f"Title set: {session.set_title(args)}")


def _handle_sessions(session: ChatSession, args: str) -> SlashResult:
    count = int(args) if args.isdigit() else 15
    rows = get_session_db().list_sessions(limit=count)
    if not rows:
        return SlashResult("No sessions yet.")
    lines = []
    for row in rows:
        marker = "*" if row["id"] == session.session_id else " "
        lines.append(
            f"{marker} {row['id']}  {_when(row.get('last_activity_at') or row.get('started_at'))}  "
            f"{row['source']:<8} {row.get('message_count', 0):>4} msgs  {_clip(row.get('title') or '', 50)}"
        )
    return SlashResult("\n".join(lines) + "\n\nResume one with /resume <id or title>.")


def _handle_resume(session: ChatSession, args: str) -> SlashResult:
    if not args:
        return _handle_sessions(session, "")
    if not session.resume(args):
        return SlashResult(
            f"No session matches {args!r} (use a full id, a unique id prefix, or the exact title)."
        )
    info = session.info()
    return SlashResult(
        f"Resumed {info['session_id']} ({info['message_count']} messages)"
        + (f": {info['title']}" if info["title"] else ""),
        ACTION_NEW,
        {"session_id": info["session_id"]},
    )


def _handle_branch(session: ChatSession, args: str) -> SlashResult:
    """Copy the conversation so far into a new session and switch to it."""
    if not session.agent.messages:
        return SlashResult("Nothing to branch yet. Send a message first.")
    session_id = session.branch(args)
    info = session.info()
    return SlashResult(
        f"Branched into {session_id} ({info['message_count']} messages copied"
        + (f": {info['title']}" if info["title"] else "")
        + ").",
        ACTION_NEW,
        {"session_id": session_id},
    )


def _handle_queue(session: ChatSession, args: str) -> SlashResult:
    """Queue a message to run after the running turn. The surface runs the returned prompt."""
    text = args.strip()
    if not text:
        return SlashResult("Usage: /queue <message>. It runs after the current turn finishes.")
    if not session.busy:
        return SlashResult("Nothing is running. Send it as a normal message instead.")
    session.queue_note(text)
    return SlashResult(f"Queued: {_clip(text, 80)}. It runs after the current turn.")


def _handle_background(session: ChatSession, args: str) -> SlashResult:
    """Run one turn in a separate session and report the result."""
    text = args.strip()
    if not text:
        return SlashResult(
            "Usage: /background <message>. It runs in a separate session and reports the result."
        )
    try:
        result = session.background(text)
    except Exception as exc:  # noqa: BLE001 - report, never crash the surface
        return SlashResult(f"Background turn failed: {type(exc).__name__}: {exc}")
    prefix = f"[{result['session_id']}] "
    body = result["response"] or "(no answer)"
    if not result["completed"]:
        body += " (the background turn did not finish)"
    return SlashResult(prefix + body, data={"session_id": result["session_id"]})


def _handle_export(session: ChatSession, args: str) -> SlashResult:
    path = args.strip().strip('"').strip("'")
    try:
        written = session.export_transcript(path)
    except (ValueError, OSError) as exc:
        return SlashResult(f"Could not export: {exc}")
    return SlashResult(f"Exported the transcript to {written}")


def _handle_pin(session: ChatSession, args: str) -> SlashResult:
    pinned = session.set_session_flag("pinned", True)
    return SlashResult(
        "This session is pinned: auto-prune will not delete it."
        if pinned
        else "This session is no longer pinned."
    )


def _handle_archive(session: ChatSession, args: str) -> SlashResult:
    archived = session.set_session_flag("archived", True)
    return SlashResult(
        "This session is archived: it is hidden from /sessions."
        if archived
        else "This session is no longer archived."
    )


def _handle_compress(session: ChatSession, args: str) -> SlashResult:
    before = len(session.agent.messages)
    if not session.agent.compress_context(focus=args or None):
        return SlashResult(
            "Nothing to compress yet: the conversation fits within the protected head and tail."
        )
    return SlashResult(f"Compressed: {before} messages -> {len(session.agent.messages)}.")


def _handle_rollback(session: ChatSession, args: str) -> SlashResult:
    """Undo the files the agent changed: the last turn, or the last ``args`` turns."""
    if args and not args.isdigit():
        return SlashResult(
            "Usage: /rollback [turns]. /rollback undoes the last turn; "
            "/rollback 3 undoes the last three. /checkpoints lists them."
        )
    turns = int(args) if args.isdigit() else 1
    if turns < 1:
        return SlashResult("turns must be 1 or more.")
    result = session.rollback_files(turns)
    if result.empty:
        return SlashResult(
            "No file checkpoints for this session. Only write_file and patch are "
            "recorded; a file changed by a terminal command is not."
        )
    return SlashResult(result.summary())


def _handle_checkpoints(session: ChatSession, args: str) -> SlashResult:
    groups = session.list_file_checkpoints()
    if not groups:
        return SlashResult(
            "No file checkpoints for this session. Only write_file and patch are "
            "recorded; a file changed by a terminal command is not."
        )
    lines = []
    for group in groups:
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(group.created_at)) if group.created_at else ""
        lines.append(f"turn {group.turn}  {when}  {len(group.changes)} file(s)")
        lines += [f"  {change.kind:<8} {change.path}" for change in group.changes]
    lines.append("Undo the last turn with /rollback, or the last N with /rollback N.")
    return SlashResult("\n".join(lines))


def _handle_stop(session: ChatSession, args: str) -> SlashResult:
    if not session.busy:
        return SlashResult("Nothing is running.")
    session.interrupt()
    return SlashResult("Stopping…")


def _handle_steer(session: ChatSession, args: str) -> SlashResult:
    if not args:
        return SlashResult("Usage: /steer <guidance for the running turn>")
    if not session.busy:
        return SlashResult("Nothing is running. Send it as a normal message instead.")
    session.steer(args)
    return SlashResult("Noted. It will be passed to the model with the next tool result.")


def _handle_quit(session: ChatSession, args: str) -> SlashResult:
    return SlashResult("Goodbye.", ACTION_QUIT)


# ── configuration ────────────────────────────────────────────────────────────────────────


def _handle_model(session: ChatSession, args: str) -> SlashResult:
    route = session.agent.route
    if not args:
        lines = [f"Model: {route.model}", f"Provider: {route.provider} ({route.api_mode})"]
        models = list_models(route.provider, route=route)
        if models:
            shown = ", ".join(model.id for model in models[:15])
            lines.append(
                f"Available: {shown}" + (f" … and {len(models) - 15} more" if len(models) > 15 else "")
            )
        lines.append(
            "Switch with /model <name> or /model <provider>:<name>. Add --global to save it as the default."
        )
        return SlashResult("\n".join(lines))
    persist = "--global" in args.split()
    target = " ".join(part for part in args.split() if part != "--global")
    result = session.switch_model(target, persist=persist)
    return SlashResult(result.message, data={"success": result.success})


def _handle_provider(session: ChatSession, args: str) -> SlashResult:
    current = session.agent.route.provider
    lines = []
    for profile in list_providers(session.agent.config):
        state = "ready" if profile.is_configured() else f"needs {' or '.join(profile.env_vars) or 'setup'}"
        lines.append(
            f"{'*' if profile.name == current else ' '} {profile.name:<12} {state:<34} {profile.description}"
        )
    return SlashResult("\n".join(lines))


def _handle_tools(session: ChatSession, args: str) -> SlashResult:
    parts = args.split()
    if len(parts) == 2 and parts[0] in ("enable", "disable"):
        action, name = parts
        if not toolset_exists(name):
            return SlashResult(f"Unknown toolset {name!r}. /tools lists them.")
        config = load_config()
        disabled = [item for item in config.get("disabled_toolsets") or [] if item != name]
        if action == "disable":
            disabled.append(name)
        config_set("disabled_toolsets", disabled)
        session.reload()
        return SlashResult(
            f"Toolset {name} {action}d. Tools now: {', '.join(sorted(session.agent.tool_names))}"
        )
    if parts:
        return SlashResult("Usage: /tools, /tools enable <toolset>, /tools disable <toolset>")
    active = session.agent.tool_names
    lines = []
    for name, spec in sorted(all_toolsets().items()):
        tools = resolve_toolset(name)
        on = sum(1 for tool in tools if tool in active)
        lines.append(
            f"{'on ' if tools and on == len(tools) else 'part' if on else 'off'}  {name:<16} "
            f"{on}/{len(tools)} tools  {spec.get('description', '')}"
        )
    return SlashResult("\n".join(lines))


def _handle_reasoning(session: ChatSession, args: str) -> SlashResult:
    if not args:
        return SlashResult(
            f"Reasoning effort: {session.agent.reasoning_effort or 'model default'}. "
            f"Set with /reasoning <{'|'.join(REASONING_LEVELS)}|default>."
        )
    level = args.strip().lower()
    if level == "default":
        level = ""
    elif level not in REASONING_LEVELS:
        return SlashResult(f"Unknown level {args!r}. Use one of: {', '.join(REASONING_LEVELS)}, default.")
    session.agent.reasoning_effort = level
    return SlashResult(f"Reasoning effort for this session: {level or 'model default'}")


def _handle_yolo(session: ChatSession, args: str) -> SlashResult:
    session.set_yolo(not session.yolo)
    if session.yolo:
        return SlashResult(
            "Approvals are OFF for this session: commands run without asking. /yolo turns them back on."
        )
    return SlashResult("Approvals are back on.")


def _handle_config(session: ChatSession, args: str) -> SlashResult:
    if not args:
        return SlashResult(
            f"Config file: {get_config_path()}\nShow a value with /config <key>, e.g. /config compression.threshold"
        )
    missing = object()
    value = get_path(load_config(), args.strip(), missing)
    return SlashResult(f"{args.strip()} is not set" if value is missing else f"{args.strip()} = {value!r}")


def _handle_reload(session: ChatSession, args: str) -> SlashResult:
    try:
        session.reload()
    except CliteError as exc:
        return SlashResult(f"Reload failed: {exc}")
    return SlashResult(
        f"Reloaded config and plugins. Model: {session.agent.route.model}; {len(session.agent.tool_names)} tools."
    )


def _handle_profile(session: ChatSession, args: str) -> SlashResult:
    active = get_active_profile_name()
    lines = [f"Active profile: {active} ({display_home()})"]
    lines += [f"{'*' if profile.name == active else ' '} {profile.name}" for profile in list_profiles()]
    lines.append("Switch by starting with `clite -p <name>`; a running session keeps its profile.")
    return SlashResult("\n".join(lines))


def _handle_verbose(session: ChatSession, args: str) -> SlashResult:
    """Set ``display.tool_progress`` for this session. Applies on the next turn."""
    level = args.strip().lower()
    if not level:
        return SlashResult(
            f"Tool progress: {session.tool_progress}. Set it with /verbose <{'|'.join(TOOL_PROGRESS_LEVELS)}>."
        )
    if level not in TOOL_PROGRESS_LEVELS:
        return SlashResult(f"Unknown level {args!r}. Use one of: {', '.join(TOOL_PROGRESS_LEVELS)}.")
    session.set_tool_progress(level)
    return SlashResult(f"Tool progress for this session: {level}.", data={"tool_progress": level})


def _handle_skin(session: ChatSession, args: str) -> SlashResult:
    """Show or change the display skin. The CLI applies ``data['skin']`` to its display."""
    name = args.strip().lower()
    if not name:
        return SlashResult(
            f"Skin: {session.skin}. Change it with /skin <name>, then /skin mono or /skin default.",
            data={"skin": session.skin},
        )
    session.set_skin(name)
    return SlashResult(f"Skin set to: {name}.", data={"skin": name})


# ── tools and skills ─────────────────────────────────────────────────────────────────────


def _handle_skills(session: ChatSession, args: str) -> SlashResult:
    needle = args.lower()
    skills = [
        skill
        for skill in discover_skills(cwd=session.agent.cwd)
        if not needle or needle in skill.name.lower() or needle in skill.description.lower()
    ]
    if not skills:
        return SlashResult("No skills match." if needle else "No skills installed.")
    lines, category = [], None
    for skill in skills:
        if skill.category != category:
            category = skill.category
            lines.append(f"{category or 'general'}:")
        lines.append(f"  /{skill.name:<28} {_clip(skill.description, 70)}")
    return SlashResult("\n".join(lines))


def _handle_plugins(session: ChatSession, args: str) -> SlashResult:
    manager = get_plugin_manager()
    manager.ensure_loaded()
    plugins = manager.list()
    if not plugins:
        return SlashResult("No plugins found.")
    lines = [
        f"{info.status:<12} {info.name:<20} {info.manifest.version:<8} {info.source:<8} "
        f"{_clip(info.error or info.manifest.description, 60)}"
        for info in plugins
    ]
    return SlashResult("\n".join(lines) + "\n\nEnable one with `clite plugins enable <name>`, then /reload.")


def _handle_hooks(session: ChatSession, args: str) -> SlashResult:
    """Shell hooks registered for this home and which of them await approval."""
    hooks = configured_hooks()
    if not hooks:
        return SlashResult(
            "No shell hooks are configured. Add them under `hooks:` in config.yaml (see `clite config path`)."
        )
    lines = []
    for hook in hooks:
        state = "approved" if is_approved(hook) else "PENDING "
        details = [f"timeout {hook.timeout:g}s"]
        if hook.matcher:
            details.insert(0, f"tools /{hook.matcher}/")
        if hook.fail_closed:
            details.append("fail closed")
        lines.append(f"{state} {hook.event:<22} {hook.command}  ({', '.join(details)})")
    if any(not is_approved(hook) for hook in hooks):
        lines.append("\nPending hooks do not run. Approve them with: clite hooks approve")
    return SlashResult("\n".join(lines))


def _handle_mcp(session: ChatSession, args: str) -> SlashResult:
    """The status of the MCP servers this session knows about."""
    from clite.tools.mcp import mcp_servers_snapshot

    servers = mcp_servers_snapshot()
    wanted = args.strip()
    if wanted:
        servers = [server for server in servers if server["name"] == wanted]
        if not servers:
            return SlashResult(f"No MCP server named {wanted!r} is connected. /mcp lists them.")
    if not servers:
        return SlashResult(
            "No MCP servers are connected. Add one with `clite mcp add` (see `clite mcp --help`)."
        )
    lines = []
    for server in servers:
        state = "up" if server["alive"] else "down"
        lines.append(
            f"{server['name']:<16} {server['transport']:<5} {state:<4} "
            f"{len(server['tools'])} tools, {server['resources']} resources, {server['prompts']} prompts"
        )
        lines += [f"    {name}" for name in server["tools"]]
        if server["tools_changed"]:
            lines.append("    its tool list changed; the new tools apply to your next session")
    return SlashResult("\n".join(lines))


def run_mcp_prompt(session: ChatSession, name: str, args: str) -> SlashResult:
    """Run an MCP prompt slash command: deliver its messages as the next user message."""
    from clite.tools.mcp import mcp_prompt_error, render_mcp_prompt

    problem = mcp_prompt_error(name, args)
    if problem is not None:
        return SlashResult(problem)
    return SlashResult(render_mcp_prompt(name, args), ACTION_SUBMIT, {"mcp_prompt": name})


def _handle_memory(session: ChatSession, args: str) -> SlashResult:
    manager = session.agent.memory
    if manager is None or manager.store is None:
        return SlashResult("Memory is disabled.")
    lines = []
    for target, label in (("memory", "MEMORY.md (agent notes)"), ("user", "USER.md (user profile)")):
        entries = manager.store.entries(target)
        used = len("\n§\n".join(entries))
        lines.append(f"{label}: {len(entries)} entries, {used}/{manager.store.limits[target]} chars")
        lines += [f"  - {_clip(entry, 110)}" for entry in entries]
    if manager.provider is not None:
        lines.append(f"External provider: {manager.provider.name}")
    return SlashResult("\n".join(lines))


def _handle_cron(session: ChatSession, args: str) -> SlashResult:
    from clite.cron.jobs import get_job_store

    jobs = get_job_store().list()
    if not jobs:
        return SlashResult("No scheduled jobs. Ask me to schedule one, or use `clite cron add`.")
    lines = [
        f"{job['id']}  {'paused ' if not job.get('enabled', True) else 'active '} {job['schedule_display']:<22} "
        f"next {_when(job.get('next_run_at'))}  {_clip(job.get('name') or job['prompt'], 50)}"
        for job in jobs
    ]
    return SlashResult("\n".join(lines))


# ── info ─────────────────────────────────────────────────────────────────────────────────


def _handle_help(session: ChatSession, args: str) -> SlashResult:
    grouped: dict[str, list[dict]] = {}
    for entry in command_catalog(session.platform, cwd=session.agent.cwd):
        grouped.setdefault(entry["category"], []).append(entry)
    lines = []
    for category, entries in grouped.items():
        lines.append(f"{category}:")
        for entry in entries:
            usage = f"/{entry['name']} {entry['args_hint']}".strip()
            lines.append(f"  {usage:<44} {_clip(entry['description'], 60)}")
    return SlashResult("\n".join(lines))


def _handle_status(session: ChatSession, args: str) -> SlashResult:
    info = session.info()
    context = info["context"]
    lines = [
        f"Session:  {info['session_id']}" + (f"  ({info['title']})" if info["title"] else ""),
        f"Model:    {info['model']} via {info['provider']}",
        f"Context:  {context['last_prompt_tokens']:,} / {context['context_length']:,} tokens "
        f"({context['usage_percent']}%), {info['message_count']} messages, {context['compression_count']} compressions",
        f"Tools:    {len(info['tools'])} from {', '.join(info['toolsets']) or 'no toolsets'}",
        f"Folder:   {info['cwd']}",
        f"State:    {'working' if info['busy'] else 'idle'}" + ("; approvals OFF" if info["yolo"] else ""),
    ]
    return SlashResult("\n".join(lines), data=info)


def _handle_usage(session: ChatSession, args: str) -> SlashResult:
    usage = session.agent.total_usage
    row = get_session_db().get_session(session.session_id) or {}
    lines = [
        f"Input tokens:       {usage.input_tokens:,}",
        f"Cached (read):      {usage.cache_read_tokens:,}",
        f"Cached (written):   {usage.cache_write_tokens:,}",
        f"Output tokens:      {usage.output_tokens:,}"
        + (f" (reasoning {usage.reasoning_tokens:,})" if usage.reasoning_tokens else ""),
        f"Model calls:        {row.get('api_call_count', 0)} over the life of this session",
    ]
    read = usage.cache_read_tokens
    if usage.prompt_tokens:
        lines.append(f"Cache hit rate:     {round(read * 100 / usage.prompt_tokens)}% of prompt tokens")
    return SlashResult("\n".join(lines))


def _handle_context(session: ChatSession, args: str) -> SlashResult:
    """Break the context window into what is actually in it: prompt tiers, tools, history."""
    agent = session.agent
    agent.ensure_session()
    status = agent.context_status()
    tiers = build_prompt_tiers(agent._prompt_inputs())
    prompt_chars = sum(len("".join(parts)) for parts in tiers.values())
    tools_chars = sum(len(json.dumps(tool, ensure_ascii=False)) for tool in agent.tools)
    history_chars = sum(len(content_text(message.get("content") or "")) for message in agent.messages)
    used = status.get("last_prompt_tokens", 0)
    window = status.get("context_length", 0)
    lines = [
        f"Context window: {used:,} / {window:,} tokens ({status.get('usage_percent', 0)}%)",
        f"Messages: {len(agent.messages)}, compressions: {status.get('compression_count', 0)}",
        "",
        "Estimated request composition (characters / 4):",
        f"  System prompt:  {prompt_chars:>8,} chars  ~{prompt_chars // 4:,} tokens",
    ]
    for tier, parts in tiers.items():
        size = len("".join(parts))
        lines.append(f"    {tier:<12} {size:>8,} chars  ~{size // 4:,} tokens  ({len(parts)} parts)")
    lines.append(
        f"  Tool schemas:   {tools_chars:>8,} chars  ~{tools_chars // 4:,} tokens  ({len(agent.tools)} tools)"
    )
    lines.append(
        f"  History:        {history_chars:>8,} chars  ~{history_chars // 4:,} tokens  ({len(agent.messages)} messages)"
    )
    lines.append("")
    lines.append(f"Tools: {len(agent.tools)} ({', '.join(sorted(agent.tool_names))})")
    return SlashResult("\n".join(lines), data=status)


def _handle_tasks(session: ChatSession, args: str) -> SlashResult:
    """Show this session's todo list."""
    todos = session.agent.todos
    items = todos.read()
    if not items:
        return SlashResult("No tasks. The list fills up as the agent plans with the `todo` tool.")
    marks = {"pending": "[ ]", "in_progress": "[>]", "completed": "[x]", "cancelled": "[~]"}
    lines = [f"{marks.get(item['status'], '[?]')} {item['id']}. {item['content']}" for item in items]
    summary = todos.summary()
    lines.append("")
    lines.append(" · ".join(f"{status}: {count}" for status, count in summary.items() if count) or "empty")
    return SlashResult("\n".join(lines), data=summary)


def _handle_logs(session: ChatSession, args: str) -> SlashResult:
    """The last lines of the agent log."""
    count = int(args) if args.isdigit() else 20
    path = get_logs_dir() / "agent.log"
    if not path.is_file():
        return SlashResult(f"No log yet at {path}. It appears once the agent logs its first line.")
    with open(path, encoding="utf-8", errors="replace") as handle:
        lines = handle.readlines()
    return SlashResult("".join(lines[-max(1, count) :]).rstrip("\n") or f"{path} is empty.")


def _handle_copy(session: ChatSession, args: str) -> SlashResult:
    """Copy the last answer to the clipboard (the CLI places ``text`` on the clipboard)."""
    answer = None
    for message in reversed(session.agent.messages):
        if message.get("role") == "assistant" and not is_internal(message):
            text = content_text(message.get("content"))
            if text.strip():
                answer = text
                break
    if answer is None:
        return SlashResult("Nothing to copy yet.")
    return SlashResult(answer, ACTION_CLIPBOARD, {"chars": len(answer)})


def _handle_insights(session: ChatSession, args: str) -> SlashResult:
    days = 30
    if args.strip():
        try:
            days = max(1, int(args.strip()))
        except ValueError:
            return SlashResult(f"Invalid days argument: {args!r}. Expected an integer.")
    db = session.agent.db
    if db is None:
        return SlashResult("Database not available.")
    from clite.state.db import format_insights

    data = db.get_insights(days=days)
    return SlashResult(format_insights(data))


def _handle_sethome(session: ChatSession, args: str) -> SlashResult:
    platform = session.platform
    origin = session.agent.session_meta.get("origin") or {}
    chat_id = origin.get("chat_id")
    if not chat_id:
        return SlashResult(f"Cannot set home channel for {platform}: no chat id found.")
    from clite.runtime.home_channel import HomeChannels

    home_channels = HomeChannels()
    home_channels.set(platform, str(chat_id))
    return SlashResult(f"Set this chat as the home channel for {platform}.")


def _handle_debug(session: ChatSession, args: str) -> SlashResult:
    agent = session.agent
    agent.ensure_session()
    tiers = build_prompt_tiers(agent._prompt_inputs())
    lines = [f"System prompt: {len(agent.system_prompt or ''):,} chars"]
    lines += [
        f"  {tier:<9} {len(parts)} parts, {sum(len(part) for part in parts):,} chars"
        for tier, parts in tiers.items()
    ]
    lines.append(f"Tools: {len(agent.tools)} ({', '.join(sorted(agent.tool_names))})")
    lines.append(f"Context engine: {agent.context_status()}")
    lines.append(f"Route: {agent.route.describe()}")
    return SlashResult("\n".join(lines))


SLASH_HANDLERS: dict[str, Callable[[ChatSession, str], SlashResult]] = {
    command.name: globals()[f"_handle_{command.name}"] for command in COMMAND_REGISTRY
}
