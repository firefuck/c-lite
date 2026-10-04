#!/usr/bin/env python3
"""Generate the reference pages that are derived from the code.

    python scripts/gen_docs.py            # rewrite docs/referensi/*.md
    python scripts/gen_docs.py --check    # exit 1 if a page is out of date (CI, test suite)

Two pages are produced, both read straight from the live registries and the source tree, so
they cannot drift from the code:

* ``docs/referensi/peta-modul.md``  every Python module: what it is and what it exports
* ``docs/referensi/katalog.md``     tools, toolsets, slash commands, CLI commands, RPC methods
                                    and events, hooks, providers, config keys, bundled extras

Never edit those files by hand. The prose around them (headings, explanations) is Indonesian
like the rest of ``docs/``; names, docstrings and help strings come from the code as they are.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "src" / "clite"
OUTPUT_DIR = ROOT / "docs" / "referensi"
HEADER = "<!-- Dibuat oleh scripts/gen_docs.py. Jangan disunting dengan tangan: ubah kodenya, lalu jalankan skrip itu. -->\n\n"

# The catalog must describe a fresh install, not the home directory of whoever runs the script.
os.environ["CLITE_HOME"] = tempfile.mkdtemp(prefix="clite-gen-docs-")
for name in [key for key in os.environ if key.startswith("CLITE_") and key != "CLITE_HOME"]:
    del os.environ[name]
sys.path.insert(0, str(ROOT / "src"))


def cell(text: Any) -> str:
    """Text made safe for a Markdown table cell."""
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def first_sentence(text: str | None) -> str:
    """The first sentence of the first paragraph (a docstring's summary may wrap)."""
    paragraph: list[str] = []
    for line in (text or "").strip().splitlines():
        if not line.strip():
            break
        paragraph.append(line.strip())
    joined = " ".join(paragraph)
    head, separator, _rest = joined.partition(". ")
    return head + "." if separator else joined


# ── module map ───────────────────────────────────────────────────────────────────────────


def public_symbols(tree: ast.Module) -> list[str]:
    names = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and not node.name.startswith("_"):
            names.append(node.name + ("()" if not isinstance(node, ast.ClassDef) else ""))
    return names


def module_map() -> str:
    lines = [
        HEADER + "# Peta modul",
        "",
        "Setiap modul Python di `src/clite`: isinya (baris pertama docstring modul) dan simbol publik",
        "yang didefinisikannya. Gunakan halaman ini untuk menemukan tempat sebuah perubahan, lalu baca",
        "`AGENTS.md` di direktori itu sebelum mengubah apa pun.",
        "",
    ]
    packages: dict[str, list[Path]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        relative = path.relative_to(PACKAGE)
        if "bundled" in relative.parts:
            continue
        packages.setdefault(relative.parent.as_posix(), []).append(path)
    # No line counts: the page should change when a module's purpose or public surface
    # changes, not on every edit.
    for package in sorted(packages, key=lambda item: (item != ".", item)):
        title = "clite/" if package == "." else f"clite/{package}/"
        lines += [f"## `{title}`", "", "| File | Isi | Simbol publik |", "| --- | --- | --- |"]
        for path in packages[package]:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            symbols = public_symbols(tree)
            shown = ", ".join(f"`{name}`" for name in symbols[:10]) + (f", … (+{len(symbols) - 10})" if len(symbols) > 10 else "")
            lines.append(f"| `{path.name}` | {cell(first_sentence(ast.get_docstring(tree)))} | {shown} |")
        lines.append("")
    lines += [f"Jumlah: {sum(len(files) for files in packages.values())} modul.", ""]
    return "\n".join(lines)


# ── catalog ──────────────────────────────────────────────────────────────────────────────


def table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    out += ["| " + " | ".join(cell(value) for value in row) + " |" for row in rows]
    return [*out, ""]


def model_fields(model: Any) -> str:
    """The field names of a Pydantic model; optional fields end with ``?``.

    Names only: the types live in ``rpc/contracts/schema.py`` and in the generated TypeScript,
    and printing them here would make this page depend on the Python version that built it.
    """
    return ", ".join(f"`{name}{'' if field.is_required() else '?'}`" for name, field in model.model_fields.items()) or "(kosong)"


def leaf_keys(node: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    keys: list[tuple[str, Any]] = []
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and value:
            keys.extend(leaf_keys(value, path))
        else:
            keys.append((path, value))
    return keys


def catalog() -> str:
    from clite.cli.main import build_parser
    from clite.core.config_defaults import DEFAULT_CONFIG
    from clite.gateway.platforms import base as platforms_base
    from clite.gateway.platforms import local, telegram  # noqa: F401 - importing registers the adapters
    from clite.plugins.hooks import FAIL_CLOSED_HOOKS, VALID_HOOKS
    from clite.plugins.manager import get_plugin_manager
    from clite.plugins.shell_hooks import SHELL_HOOK_EVENTS
    from clite.providers.registry import list_providers
    from clite.rpc.contracts import schema  # noqa: F401 - importing registers everything
    from clite.rpc.contracts.base import EVENTS, METHODS, PROTOCOL_VERSION, SERVER_REQUESTS
    from clite.runtime.commands import COMMAND_REGISTRY
    from clite.skills.catalog import discover_skills
    from clite.tools.registry import discover_builtin_tools, registry
    from clite.tools.toolsets import TOOLSETS, resolve_toolset

    discover_builtin_tools()
    lines = [
        HEADER + "# Katalog",
        "",
        "Semua yang terdaftar di sebuah instalasi baru, dibaca langsung dari registry di kode.",
        "",
    ]

    lines += ["## Tool", ""]
    lines += table(
        ["Tool", "Toolset", "Paralel", "Deskripsi"],
        [[f"`{entry.name}`", f"`{entry.toolset}`", entry.parallel, first_sentence(entry.description)]
         for entry in sorted(registry.entries(), key=lambda item: (item.toolset, item.name))],
    )

    lines += ["## Toolset", ""]
    lines += table(
        ["Toolset", "Deskripsi", "Berisi (setelah `includes` diurai)"],
        [[f"`{name}`", spec.get("description", ""), ", ".join(f"`{tool}`" for tool in resolve_toolset(name))]
         for name, spec in TOOLSETS.items()],
    )

    lines += ["## Slash command", ""]
    lines += table(
        ["Perintah", "Alias", "Kategori", "Argumen", "Saat sibuk", "Hanya CLI", "Deskripsi"],
        [[f"`/{command.name}`", ", ".join(f"`/{alias}`" for alias in command.aliases), command.category,
          f"`{command.args_hint}`" if command.args_hint else "", command.busy_policy, "ya" if command.cli_only else "",
          command.description] for command in COMMAND_REGISTRY],
    )

    parser = build_parser()
    subparsers = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    helps = {action.dest: action.help or "" for action in subparsers._choices_actions}
    lines += ["## Perintah CLI", ""]
    rows = []
    for name, sub in subparsers.choices.items():
        nested = next((action for action in sub._actions if isinstance(action, argparse._SubParsersAction)), None)
        rows.append([f"`clite {name}`", helps.get(name, ""), ", ".join(f"`{child}`" for child in nested.choices) if nested else ""])
    lines += table(["Perintah", "Fungsi", "Sub-perintah"], rows)

    lines += [f"## Protokol JSON-RPC (versi {PROTOCOL_VERSION})", "", "### Method", ""]
    lines += table(
        ["Method", "Parameter", "Hasil", "Keterangan"],
        [[f"`{name}`", model_fields(spec.params), model_fields(spec.result), spec.description] for name, spec in METHODS.items()],
    )
    lines += ["### Event", ""]
    lines += table(["Event", "Payload"], [[f"`{name}`", model_fields(model)] for name, model in EVENTS.items()])
    lines += ["### Permintaan dari server ke klien", ""]
    lines += table(
        ["Permintaan", "Parameter", "Jawaban", "Keterangan"],
        [[f"`{name}`", model_fields(spec.params), model_fields(spec.result), spec.description] for name, spec in SERVER_REQUESTS.items()],
    )

    lines += ["## Hook", ""]
    lines += table(
        ["Hook", "Bisa dari shell hook", "Gagal = blokir"],
        [[f"`{name}`", "ya" if name in SHELL_HOOK_EVENTS else "", "ya" if name in FAIL_CLOSED_HOOKS else ""]
         for name in sorted(VALID_HOOKS)],
    )

    lines += ["## Provider bawaan", ""]
    lines += table(
        ["Provider", "Alias", "`api_mode`", "Variabel kunci", "Base URL", "Model default"],
        [[f"`{profile.name}`", ", ".join(f"`{alias}`" for alias in profile.aliases), f"`{profile.api_mode}`",
          ", ".join(f"`{variable}`" for variable in profile.env_vars), profile.base_url, profile.default_model]
         for profile in list_providers()],
    )

    lines += ["## Platform gateway", ""]
    lines += table(["Platform"], [[f"`{name}`"] for name in sorted(platforms_base.PLATFORMS)])

    manager = get_plugin_manager()
    manager.discover()
    lines += ["## Plugin bawaan", ""]
    lines += table(
        ["Plugin", "Jenis", "Deskripsi"],
        [[f"`{info.name}`", info.manifest.kind, info.manifest.description] for info in manager.list() if info.source == "bundled"],
    )

    lines += ["## Skill bawaan", ""]
    lines += table(
        ["Skill", "Kategori", "Deskripsi"],
        [[f"`{skill.name}`", skill.category, skill.description] for skill in discover_skills(cwd=os.environ["CLITE_HOME"])],
    )

    lines += ["## Kunci konfigurasi", "", "Nilai default dari `clite/core/config_defaults.py`. Penjelasan tiap kunci ada di file itu.", ""]
    lines += table(
        ["Kunci", "Default"],
        [[f"`{key}`", f"`{json.dumps(value, ensure_ascii=False)}`"] for key, value in leaf_keys(DEFAULT_CONFIG)],
    )
    return "\n".join(lines)


PAGES = {"peta-modul.md": module_map, "katalog.md": catalog}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if a generated page is out of date")
    args = parser.parse_args(argv)
    stale = []
    for name, build in PAGES.items():
        path = OUTPUT_DIR / name
        content = build().rstrip("\n") + "\n"
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                stale.append(name)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print(f"out of date: {', '.join(stale)}. Run: python scripts/gen_docs.py", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
