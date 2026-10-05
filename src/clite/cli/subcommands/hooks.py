"""``clite hooks``: review, approve, revoke and try the shell hooks from ``config.yaml``."""

from __future__ import annotations

import argparse
import json
import sys

from clite.plugins.shell_hooks import (
    ShellHook,
    approve_hooks,
    configured_hooks,
    evaluate,
    is_approved,
    revoke_hooks,
    run_hook,
)

SAMPLE_TOOL_INPUT = {"command": "echo hello"}


def _describe(hook: ShellHook) -> str:
    details = [f"timeout {hook.timeout:g}s"]
    if hook.matcher:
        details.insert(0, f"tools matching /{hook.matcher}/")
    if hook.fail_closed:
        details.append("fail closed")
    return f"{hook.event:<22} {hook.command}  ({', '.join(details)})"


def run_list(args: argparse.Namespace) -> int:
    hooks = configured_hooks()
    if not hooks:
        print("No shell hooks are configured. Add them under `hooks:` in config.yaml (see `clite config path`).")
        return 0
    for hook in hooks:
        print(f"{'approved' if is_approved(hook) else 'PENDING ':<9} {_describe(hook)}")
    if any(not is_approved(hook) for hook in hooks):
        print("\nPending hooks do not run. Read each command, then approve them with: clite hooks approve")
    return 0


def run_approve(args: argparse.Namespace) -> int:
    pending = [hook for hook in configured_hooks() if not is_approved(hook)]
    if not pending:
        print("Nothing to approve.")
        return 0
    print("These commands will run with your permissions, outside the command-approval prompt:\n")
    for hook in pending:
        print(f"  {_describe(hook)}")
    if not args.yes:
        if not sys.stdin.isatty():
            print("\nNot approved: re-run with --yes, or run this command in a terminal to confirm.")
            return 1
        if input(f"\nApprove {len(pending)} hook(s)? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Nothing was approved.")
            return 1
    print(f"\nApproved {approve_hooks(pending)} hook(s). They take effect in new sessions (or after /reload).")
    return 0


def run_revoke(args: argparse.Namespace) -> int:
    if not args.all and not args.hook_command:
        print("Say which command to revoke, or use --all.")
        return 2
    removed = revoke_hooks(None if args.all else args.hook_command)
    print(f"Revoked {removed} approval(s)." if removed else "No matching approval.")
    return 0


def run_test(args: argparse.Namespace) -> int:
    """Run the hooks for one event with a sample payload and show what each would do."""
    hooks = [hook for hook in configured_hooks() if hook.event == args.event]
    if not hooks:
        print(f"No hooks are configured for {args.event}.")
        return 1
    payload = {"session_id": "hook-test", "tool_name": args.tool, "args": json.loads(args.input)}
    for hook in hooks:
        print(f"$ {hook.command}")
        if not hook.matches_tool(args.tool) and hook.matcher:
            print(f"  skipped: /{hook.matcher}/ does not match tool {args.tool!r}")
            continue
        run = run_hook(hook, payload)
        if run.error:
            print(f"  error: {run.error}")
        else:
            print(f"  exit {run.exit_code} in {run.seconds:.2f}s")
            for label, text in (("stdout", run.stdout), ("stderr", run.stderr)):
                if text.strip():
                    print(f"  {label}: {text.strip()[:500]}")
        print(f"  result: {json.dumps(evaluate(hook, run)) if evaluate(hook, run) is not None else 'no effect'}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("hooks", help="review, approve or test shell hooks from config.yaml")
    parser.set_defaults(handler=run_list)
    actions = parser.add_subparsers(dest="hooks_action")
    actions.add_parser("list", help="show configured hooks and whether each is approved").set_defaults(handler=run_list)
    approve = actions.add_parser("approve", help="approve the pending hooks so they run")
    approve.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    approve.set_defaults(handler=run_approve)
    revoke = actions.add_parser("revoke", help="withdraw approval")
    revoke.add_argument("hook_command", nargs="?", metavar="COMMAND", help="the hook command, exactly as configured")
    revoke.add_argument("--all", action="store_true")
    revoke.set_defaults(handler=run_revoke)
    test = actions.add_parser("test", help="run the hooks for an event with a sample payload")
    test.add_argument("event")
    test.add_argument("--tool", default="terminal", help="tool name in the sample payload (default: terminal)")
    test.add_argument("--input", default=json.dumps(SAMPLE_TOOL_INPUT), help="tool arguments as JSON")
    test.set_defaults(handler=run_test)
