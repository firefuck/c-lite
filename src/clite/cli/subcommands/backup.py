"""``clite backup``: archive and restore the agent's home directory."""

from __future__ import annotations

import argparse
import os
import tarfile
import time
from pathlib import Path

from clite.core.constants import get_home
from clite.core.errors import CliteError

BACKUP_INCLUDED_NAMES = ("config.yaml", "memories", "skills", "sessions", "cron")
SECRET_NAMES = (".env", "auth.json")


def create_backup(target_path: Path | str | None = None, *, include_secrets: bool = False) -> Path:
    home = get_home()
    if target_path:
        out = Path(target_path).resolve()
    else:
        out = Path(f"clite-backup-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz").resolve()

    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w:gz") as tar:
        for name in BACKUP_INCLUDED_NAMES:
            p = home / name
            if p.exists():
                tar.add(p, arcname=name)
        if include_secrets:
            for name in SECRET_NAMES:
                p = home / name
                if p.exists():
                    tar.add(p, arcname=name)

    if include_secrets:
        try:
            os.chmod(out, 0o600)
        except OSError:
            pass

    return out


def restore_backup(archive_path: Path | str, *, force: bool = False) -> None:
    path = Path(archive_path).resolve()
    if not path.is_file():
        raise CliteError(f"backup archive not found: {path}")

    home = get_home()
    home.mkdir(parents=True, exist_ok=True)

    # Check if home has existing data
    has_existing = any((home / name).exists() for name in (*BACKUP_INCLUDED_NAMES, *SECRET_NAMES))
    if has_existing and not force:
        raise CliteError(f"home directory {home} is not empty; use --force to overwrite")

    with tarfile.open(path, "r:gz") as tar:
        # Safe extraction
        for member in tar.getmembers():
            # Disallow absolute paths or parent directory traversal
            if member.name.startswith("/") or ".." in Path(member.name).parts:
                raise CliteError(f"unsafe member path in archive: {member.name}")
        tar.extractall(path=home)


def run_backup(args: argparse.Namespace) -> int:
    action = args.backup_action
    if action == "create":
        out = create_backup(args.path, include_secrets=args.include_secrets)
        print(f"Backup created at: {out}")
        return 0
    if action == "restore":
        restore_backup(args.archive, force=args.force)
        print(f"Backup restored to: {get_home()}")
        return 0
    return 1


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("backup", help="archive or restore the agent's home directory")
    actions = parser.add_subparsers(dest="backup_action", required=True)

    create_parser = actions.add_parser("create", help="create a backup archive")
    create_parser.add_argument("path", nargs="?", help="target archive path (.tar.gz)")
    create_parser.add_argument(
        "--include-secrets", action="store_true", help="include .env and auth.json (mode 0600)"
    )

    restore_parser = actions.add_parser("restore", help="restore from a backup archive")
    restore_parser.add_argument("archive", help="path to backup archive (.tar.gz)")
    restore_parser.add_argument("--force", action="store_true", help="overwrite existing home data")

    parser.set_defaults(handler=run_backup)
