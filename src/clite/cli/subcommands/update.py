"""``clite update``: check for updates and upgrade the installation."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from clite import __version__
from clite.core.errors import CliteError


def detect_install_method() -> str:
    """Detect whether c-lite is installed via git, pipx, or pip."""
    # Check if running from a git checkout
    repo_root = Path(__file__).resolve().parents[4]
    if (repo_root / ".git").is_dir():
        return "git"
    if "pipx" in sys.prefix or os.environ.get("PIPX_HOME"):
        return "pipx"
    return "pip"


def check_latest_version(index_url: str | None = None) -> tuple[str, str, bool]:
    """Return (current_version, latest_version, has_update)."""
    current = __version__

    # Testing hook: allow mock latest version via environment
    mock_ver = os.environ.get("CLITE_UPDATE_MOCK_VERSION")
    if mock_ver:
        return current, mock_ver, mock_ver != current

    url = index_url or "https://pypi.org/pypi/c-lite/json"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": f"c-lite/{current}"})  # noqa: S310 - PyPI over https, or the index the user named
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310 - PyPI over https, or the index the user named
            data = json.loads(resp.read().decode("utf-8"))
            latest = str(data.get("info", {}).get("version", current))
    except Exception as exc:
        raise CliteError(f"could not check for updates from {url}: {exc}") from exc

    return current, latest, latest != current


def run_update(args: argparse.Namespace) -> int:
    current, latest, has_update = check_latest_version(args.index_url)
    method = detect_install_method()

    if args.check:
        print(f"c-lite current: {current}, latest: {latest}")
        if has_update:
            print(f"Update available: {latest} (installed via {method})")
        else:
            print("c-lite is up to date.")
        return 0

    if not has_update:
        print(f"c-lite is already up to date ({current}).")
        return 0

    print(f"Updating c-lite {current} -> {latest} via {method}…")
    if method == "git":
        repo_root = Path(__file__).resolve().parents[4]
        res = subprocess.run(  # noqa: S603 - git pull in this install's own checkout
            ["git", "-C", str(repo_root), "pull", "--ff-only"],  # noqa: S607 - the user's git on PATH
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            raise CliteError(f"git pull failed: {res.stderr.strip()}")
    elif method == "pipx":
        pipx_bin = shutil.which("pipx") or "pipx"
        res = subprocess.run([pipx_bin, "upgrade", "c-lite"], capture_output=True, text=True)  # noqa: S603 - fixed pipx argv, no shell
        if res.returncode != 0:
            raise CliteError(f"pipx upgrade failed: {res.stderr.strip()}")
    else:
        res = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--upgrade", "c-lite"], capture_output=True, text=True
        )
        if res.returncode != 0:
            raise CliteError(f"pip install failed: {res.stderr.strip()}")

    # Run config migration if needed
    from clite.core.config import migrate_config_file

    migrate_config_file()

    print(f"✓ Updated c-lite to {latest}.")
    return 0


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("update", help="check for updates and upgrade c-lite")
    parser.add_argument("--check", action="store_true", help="only check for newer version without upgrading")
    parser.add_argument("--index-url", help="custom package index JSON URL to check against")
    parser.set_defaults(handler=run_update)
