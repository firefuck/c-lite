#!/usr/bin/env python3
"""Generate the reference pages that are derived from the code.

    python scripts/gen_docs.py                    # rewrite docs/referensi/*.md and the site pages
    python scripts/gen_docs.py --target docs      # only docs/referensi/*.md
    python scripts/gen_docs.py --target site      # only website/content/*/reference/*.md
    python scripts/gen_docs.py --check            # exit 1 if a page is out of date (CI, test suite)

Four files come out of this, all read straight from the live registries and the source tree, so
they cannot drift from the code:

* ``docs/referensi/peta-modul.md``      every Python module: what it is and what it exports
* ``docs/referensi/katalog.md``         tools, toolsets, slash commands, CLI commands, RPC
                                        methods and events, hooks, providers, config keys,
                                        bundled extras
* ``website/content/{id,en}/reference/*.md``  the same catalog, split for a reader who *uses*
                                        the program rather than changes it: commands,
                                        configuration, and tools

The first two are developer documentation, written in Indonesian like the rest of ``docs/``. The
site pages exist in both languages, so their headings and table headers are translated here while
the data in the cells stays exactly what the code says. Never edit any of the four by hand.
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
SITE_DIR = ROOT / "website" / "content"
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
        if isinstance(
            node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
        ) and not node.name.startswith("_"):
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
            shown = ", ".join(f"`{name}`" for name in symbols[:10]) + (
                f", … (+{len(symbols) - 10})" if len(symbols) > 10 else ""
            )
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
    return (
        ", ".join(
            f"`{name}{'' if field.is_required() else '?'}`" for name, field in model.model_fields.items()
        )
        or "(kosong)"
    )


def leaf_keys(node: dict[str, Any], prefix: str = "") -> list[tuple[str, Any]]:
    keys: list[tuple[str, Any]] = []
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and value:
            keys.extend(leaf_keys(value, path))
        else:
            keys.append((path, value))
    return keys


# Every table header and in-cell word that has to be translated for the site pages. The data in
# the cells is the same in both languages; only these labels differ.
WORDS: dict[str, dict[str, str]] = {
    "id": {
        "tool": "Tool",
        "toolset": "Toolset",
        "parallel": "Paralel",
        "description": "Deskripsi",
        "toolset_contents": "Berisi (setelah `includes` diurai)",
        "command": "Perintah",
        "category": "Kategori",
        "arguments": "Argumen",
        "function": "Fungsi",
        "subcommands": "Sub-perintah",
        "when_busy": "Saat sibuk",
        "cli_only": "Hanya CLI",
        "method": "Method",
        "event": "Event",
        "result": "Hasil",
        "notes": "Keterangan",
        "server_requests": "Permintaan dari server ke klien",
        "request": "Permintaan",
        "answer": "Jawaban",
        "hook": "Hook",
        "shell_hook": "Bisa dari shell hook",
        "fails_closed": "Gagal = blokir",
        "provider": "Provider",
        "platform": "Platform",
        "key_variable": "Variabel kunci",
        "default_model": "Model default",
        "kind": "Jenis",
        "skill": "Skill",
        "config_key": "Kunci",
        "default": "Default",
        "yes": "ya",
    },
    "en": {
        "tool": "Tool",
        "toolset": "Toolset",
        "parallel": "Parallel",
        "description": "Description",
        "toolset_contents": "Contents (after `includes` is resolved)",
        "command": "Command",
        "category": "Category",
        "arguments": "Arguments",
        "function": "What it does",
        "subcommands": "Subcommands",
        "when_busy": "When busy",
        "cli_only": "CLI only",
        "method": "Method",
        "event": "Event",
        "result": "Result",
        "notes": "Description",
        "server_requests": "Requests from the server to the client",
        "request": "Request",
        "answer": "Answer",
        "hook": "Hook",
        "shell_hook": "Runnable as a shell hook",
        "fails_closed": "Fails closed",
        "provider": "Provider",
        "platform": "Platform",
        "key_variable": "Key variable",
        "default_model": "Default model",
        "kind": "Kind",
        "skill": "Skill",
        "config_key": "Key",
        "default": "Default",
        "yes": "yes",
    },
}

# Section order of the catalog, and the heading each section gets per language. The ``rpc``
# heading carries the protocol version.
CATALOG_LAYOUT = [
    "tools",
    "toolsets",
    "slash",
    "cli",
    "rpc",
    "hooks",
    "providers",
    "platforms",
    "plugins",
    "skills",
    "config",
]

HEADINGS: dict[str, dict[str, str]] = {
    "id": {
        "tools": "Tool",
        "toolsets": "Toolset",
        "slash": "Slash command",
        "cli": "Perintah CLI",
        "rpc": "Protokol JSON-RPC (versi {version})",
        "hooks": "Hook",
        "providers": "Provider bawaan",
        "platforms": "Platform gateway",
        "plugins": "Plugin bawaan",
        "skills": "Skill bawaan",
        "config": "Kunci konfigurasi",
    },
    "en": {
        "tools": "Tools",
        "toolsets": "Toolsets",
        "slash": "Slash commands",
        "cli": "CLI commands",
        "rpc": "JSON-RPC protocol (version {version})",
        "hooks": "Hooks",
        "providers": "Built-in providers",
        "platforms": "Gateway platforms",
        "plugins": "Bundled plugins",
        "skills": "Bundled skills",
        "config": "Configuration keys",
    },
}


def catalog_sections(language: str) -> tuple[dict[str, list[str]], int]:
    """Every section of the catalog, keyed by a stable name, as finished Markdown lines.

    ``language`` picks the table headers and the few words inside cells; the data itself comes
    from the registries and reads the same in both languages. The second return value is the
    protocol version the RPC section was built against, which its heading needs.
    """
    from clite.cli.main import build_parser
    from clite.core.config_defaults import DEFAULT_CONFIG
    from clite.gateway.platforms import base as platforms_base
    from clite.gateway.platforms import (  # noqa: F401 - importing registers the adapters
        discord,
        local,
        slack,
        telegram,
    )
    from clite.plugins.hooks import FAIL_CLOSED_HOOKS, VALID_HOOKS
    from clite.plugins.manager import ensure_plugins_loaded, get_plugin_manager
    from clite.plugins.shell_hooks import SHELL_HOOK_EVENTS
    from clite.providers.registry import list_providers
    from clite.rpc.contracts import schema  # noqa: F401 - importing registers everything
    from clite.rpc.contracts.base import EVENTS, METHODS, PROTOCOL_VERSION, SERVER_REQUESTS
    from clite.runtime.commands import COMMAND_REGISTRY
    from clite.skills.catalog import discover_skills
    from clite.tools.registry import discover_builtin_tools, registry
    from clite.tools.toolsets import TOOLSETS, resolve_toolset

    w = WORDS[language]
    discover_builtin_tools()
    ensure_plugins_loaded()  # bundled platform plugins extend the registry in a fresh install
    sections: dict[str, list[str]] = {}

    sections["tools"] = table(
        [w["tool"], w["toolset"], w["parallel"], w["description"]],
        [
            [f"`{entry.name}`", f"`{entry.toolset}`", entry.parallel, first_sentence(entry.description)]
            for entry in sorted(registry.entries(), key=lambda item: (item.toolset, item.name))
        ],
    )

    sections["toolsets"] = table(
        [w["toolset"], w["description"], w["toolset_contents"]],
        [
            [
                f"`{name}`",
                spec.get("description", ""),
                ", ".join(f"`{tool}`" for tool in resolve_toolset(name)),
            ]
            for name, spec in TOOLSETS.items()
        ],
    )

    sections["slash"] = table(
        [
            w["command"],
            "Alias",
            w["category"],
            w["arguments"],
            w["when_busy"],
            w["cli_only"],
            w["description"],
        ],
        [
            [
                f"`/{command.name}`",
                ", ".join(f"`/{alias}`" for alias in command.aliases),
                command.category,
                f"`{command.args_hint}`" if command.args_hint else "",
                command.busy_policy,
                w["yes"] if command.cli_only else "",
                command.description,
            ]
            for command in COMMAND_REGISTRY
        ],
    )

    parser = build_parser()
    subparsers = next(action for action in parser._actions if isinstance(action, argparse._SubParsersAction))
    helps = {action.dest: action.help or "" for action in subparsers._choices_actions}
    rows = []
    for name, sub in subparsers.choices.items():
        nested = next(
            (action for action in sub._actions if isinstance(action, argparse._SubParsersAction)), None
        )
        rows.append(
            [
                f"`clite {name}`",
                helps.get(name, ""),
                ", ".join(f"`{child}`" for child in nested.choices) if nested else "",
            ]
        )
    sections["cli"] = table([w["command"], w["function"], w["subcommands"]], rows)

    sections["rpc"] = [f"### {w['method']}", ""]
    sections["rpc"] += table(
        [w["method"], "Parameter", w["result"], w["notes"]],
        [
            [f"`{name}`", model_fields(spec.params), model_fields(spec.result), spec.description]
            for name, spec in METHODS.items()
        ],
    )
    sections["rpc"] += [f"### {w['event']}", ""]
    sections["rpc"] += table(
        [w["event"], "Payload"], [[f"`{name}`", model_fields(model)] for name, model in EVENTS.items()]
    )
    sections["rpc"] += [f"### {w['server_requests']}", ""]
    sections["rpc"] += table(
        [w["request"], "Parameter", w["answer"], w["notes"]],
        [
            [f"`{name}`", model_fields(spec.params), model_fields(spec.result), spec.description]
            for name, spec in SERVER_REQUESTS.items()
        ],
    )

    sections["hooks"] = table(
        [w["hook"], w["shell_hook"], w["fails_closed"]],
        [
            [
                f"`{name}`",
                w["yes"] if name in SHELL_HOOK_EVENTS else "",
                w["yes"] if name in FAIL_CLOSED_HOOKS else "",
            ]
            for name in sorted(VALID_HOOKS)
        ],
    )

    sections["providers"] = table(
        [w["provider"], "Alias", "`api_mode`", w["key_variable"], "Base URL", w["default_model"]],
        [
            [
                f"`{profile.name}`",
                ", ".join(f"`{alias}`" for alias in profile.aliases),
                f"`{profile.api_mode}`",
                ", ".join(f"`{variable}`" for variable in profile.env_vars),
                profile.base_url,
                profile.default_model,
            ]
            for profile in list_providers()
        ],
    )

    sections["platforms"] = table(
        [w["platform"]], [[f"`{name}`"] for name in sorted(platforms_base.PLATFORMS)]
    )

    manager = get_plugin_manager()
    manager.discover()
    sections["plugins"] = table(
        ["Plugin", w["kind"], w["description"]],
        [
            [f"`{info.name}`", info.manifest.kind, info.manifest.description]
            for info in manager.list()
            if info.source == "bundled"
        ],
    )

    sections["skills"] = table(
        [w["skill"], w["category"], w["description"]],
        [
            [f"`{skill.name}`", skill.category, skill.description]
            for skill in discover_skills(cwd=os.environ["CLITE_HOME"])
        ],
    )

    sections["config"] = table(
        [w["config_key"], w["default"]],
        [
            [f"`{key}`", f"`{json.dumps(value, ensure_ascii=False)}`"]
            for key, value in leaf_keys(DEFAULT_CONFIG)
        ],
    )
    return sections, PROTOCOL_VERSION


# The intro and the note under each title of the developer-facing catalog. The site pages carry
# their own, translated, text in SITE_PAGES.
CATALOG_INTRO = [
    "Semua yang terdaftar di sebuah instalasi baru, dibaca langsung dari registry di kode.",
    "",
]
CONFIG_NOTE = "Nilai default dari `clite/core/config_defaults.py`. Penjelasan tiap kunci ada di file itu."


def catalog() -> str:
    sections, version = catalog_sections("id")
    lines = [HEADER + "# Katalog", "", *CATALOG_INTRO]
    for key in CATALOG_LAYOUT:
        lines += [f"## {HEADINGS['id'][key].format(version=version)}", ""]
        if key == "config":
            lines += [CONFIG_NOTE, ""]
        lines += sections[key]
    return "\n".join(lines)


# ── the user-facing reference pages of the site ──────────────────────────────────────────

SITE_INTRO = {
    "id": "Halaman ini dibuat dari kode oleh `scripts/gen_docs.py`, jadi isinya tidak pernah tertinggal dari programnya. Jangan disunting dengan tangan: ubah kodenya, lalu jalankan skrip itu.",
    "en": "This page is generated from the code by `scripts/gen_docs.py`, so it can never fall behind the program. Do not edit it by hand: change the code, then run that script.",
}

SITE_PAGES: dict[str, dict[str, dict[str, Any]]] = {
    "commands": {
        "id": {
            "title": "Rujukan perintah",
            "note": "Setiap perintah slash dan sub-perintah `clite`, dibaca dari registry di kode.",
            "parts": [("Perintah slash", "slash"), ("Perintah CLI", "cli")],
        },
        "en": {
            "title": "Command reference",
            "note": "Every slash command and `clite` subcommand, read from the registry in the code.",
            "parts": [("Slash commands", "slash"), ("CLI commands", "cli")],
        },
    },
    "config": {
        "id": {
            "title": "Rujukan konfigurasi",
            "note": "Nilai bawaan setiap kunci. Menghapus sebuah kunci dari berkas Anda berarti kembali ke nilai ini, bukan mematikannya.",
            "parts": [
                ("Kunci konfigurasi", "config"),
                ("Provider bawaan", "providers"),
                ("Platform gateway", "platforms"),
            ],
        },
        "en": {
            "title": "Configuration reference",
            "note": "The default of every key. Removing a key from your file means going back to this value, not turning it off.",
            "parts": [
                ("Configuration keys", "config"),
                ("Built-in providers", "providers"),
                ("Gateway platforms", "platforms"),
            ],
        },
    },
    "tools": {
        "id": {
            "title": "Rujukan tool",
            "note": "Apa yang bisa dipanggil model, apa isi tiap toolset, dan apa yang dibawa paket: plugin, skill, dan hook.",
            "parts": [
                ("Tool", "tools"),
                ("Toolset", "toolsets"),
                ("Hook", "hooks"),
                ("Plugin bawaan", "plugins"),
                ("Skill bawaan", "skills"),
            ],
        },
        "en": {
            "title": "Tool reference",
            "note": "What the model can call, what each toolset holds, and what the package ships: plugins, skills and hooks.",
            "parts": [
                ("Tools", "tools"),
                ("Toolsets", "toolsets"),
                ("Hooks", "hooks"),
                ("Bundled plugins", "plugins"),
                ("Bundled skills", "skills"),
            ],
        },
    },
}


def site_pages() -> dict[Path, str]:
    """The reference pages of the documentation site, as ``path -> content``."""
    sections: dict[str, dict[str, list[str]]] = {}
    for language in ("id", "en"):
        sections[language], _version = catalog_sections(language)
    pages: dict[Path, str] = {}
    for name, by_language in SITE_PAGES.items():
        for language, spec in by_language.items():
            lines = [f"# {spec['title']}", "", SITE_INTRO[language], "", spec["note"], ""]
            for heading, key in spec["parts"]:
                lines += [f"## {heading}", ""] + sections[language][key]
            pages[SITE_DIR / language / "reference" / f"{name}.md"] = "\n".join(lines).rstrip("\n") + "\n"
    return pages


PAGES = {"peta-modul.md": module_map, "katalog.md": catalog}
SITE_TARGET = "site"
DOCS_TARGET = "docs"


def generated(target: str) -> dict[Path, str]:
    """Every page this run would write, as ``path -> content``, for the chosen target."""
    pages: dict[Path, str] = {}
    if target in {DOCS_TARGET, "all"}:
        pages.update({OUTPUT_DIR / name: build() for name, build in PAGES.items()})
    if target in {SITE_TARGET, "all"}:
        pages.update(site_pages())
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--target",
        choices=["all", DOCS_TARGET, SITE_TARGET],
        default="all",
        help="which pages to write: the developer docs, the site reference, or both",
    )
    parser.add_argument("--check", action="store_true", help="exit 1 if a generated page is out of date")
    args = parser.parse_args(argv)
    stale = []
    for path, content in generated(args.target).items():
        content = content.rstrip("\n") + "\n"
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                stale.append(str(path.relative_to(ROOT)))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        print(
            f"out of date: {', '.join(stale)}. Run: python scripts/gen_docs.py",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
