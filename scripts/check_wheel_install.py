#!/usr/bin/env python3
"""Exercise an installed wheel outside the checkout, with an isolated mock-only home."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import clite


def main() -> None:
    package = Path(clite.__file__).resolve().parent
    if not package.is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError("Expected a wheel installed in this virtualenv, not an editable checkout")
    resources = (
        "bundled/plugins/audit-log/plugin.yaml",
        "bundled/plugins/audit-log/__init__.py",
        "bundled/plugins/model-providers/mock/plugin.yaml",
        "bundled/plugins/model-providers/mock/__init__.py",
        "bundled/skills/meta/skill-authoring/SKILL.md",
        "server/static/index.html",
        "server/static/app.js",
        "server/static/rpc.js",
        "server/static/style.css",
        "tui_dist/clite-tui.mjs",
        "tui_dist/build-info.json",
    )
    for name in resources:
        asset = package / name
        if not asset.is_file() or not asset.stat().st_size:
            raise RuntimeError(f"The wheel is missing a required resource: {name}")

    command = Path(sys.executable).parent / ("clite.exe" if os.name == "nt" else "clite")
    with tempfile.TemporaryDirectory(prefix="clite-wheel-smoke-") as directory:
        smoke_home = Path(directory) / "profile"
        smoke_home.mkdir()
        (smoke_home / "config.yaml").write_text("model:\n  provider: mock\n  default: mock-1\n", encoding="utf-8")
        # No inherited profile, Python import path, or service credential enters the smoke run.
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("CLITE_", "PYTHON"))
               and not key.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))}
        env.update(CLITE_HOME=str(smoke_home), CLITE_PYTHON=sys.executable, NO_COLOR="1")

        def run(*args: str, input_text: str | None = None) -> str:
            result = subprocess.run([str(command), *args], cwd=directory, env=env,
                                    input=input_text, capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise RuntimeError(f"clite {' '.join(args)} failed ({result.returncode}):\n"
                                   f"{result.stdout}\n{result.stderr}")
            return result.stdout

        assert clite.__version__ in run("--version")
        run("doctor")
        assert "You said: wheel smoke" in run("chat", "-q", "wheel smoke", "--provider", "mock")
        assert "audit-log" in run("plugins", "list")
        assert "skill-authoring" in run("skills", "list")
        assert "Usage: clite tui" in run("tui", "--help")
        assert "You said: wheel tui" in run("tui", input_text="wheel tui\n/quit\n")
    print("Installed wheel passed: CLI, doctor, mock turns, plugins, skills, dashboard assets and TUI")


if __name__ == "__main__":
    main()
