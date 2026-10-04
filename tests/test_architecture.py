"""Rules about the shape of the codebase, checked mechanically.

These tests read the source instead of running it. They exist so that a rule written in
``AGENTS.md`` fails the build when it is broken, instead of depending on a reviewer noticing.

* Imports point down the layers (``docs/arsitektur/01-lapisan.md``).
* Every key in ``DEFAULT_CONFIG`` has code that reads it.
* The generated TypeScript contracts and the generated reference pages match the code.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

from clite.core.config_defaults import DEFAULT_CONFIG

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "src" / "clite"

# ── layering ─────────────────────────────────────────────────────────────────────────────

# A module may import, at module level, only from areas with a LOWER rank than its own.
# Two areas with the same rank never import each other.
LAYER_RANK = {
    "(root)": 0,  # clite/__init__.py: the version string
    "core": 0,
    "state": 1,
    "providers": 1,
    "plugins.hooks": 1,  # the hook bus is a leaf so that every layer can fire hooks
    "skills": 2,
    "tools": 3,
    "agent": 4,
    "plugins": 5,  # manager, context, manifest, shell hooks
    "cron": 6,
    "runtime": 7,
    "rpc": 8,
    "gateway": 8,
    "server": 9,  # hosts the rpc server over WebSocket
    "acp": 9,
    "cli": 10,  # wires everything together
    "__main__": 11,
}

# Imports that point UP the layers. Each is made inside a function (so there is no import
# cycle) and each is a deliberate inversion; a new entry needs a reason.
ALLOWED_UPWARD_LAZY_IMPORTS = {
    ("clite.tools.builtin.delegate", "agent"),  # the tool is a thin wrapper over agent.delegation
    ("clite.tools.builtin.cronjob", "cron"),  # the tool edits the job store
    ("clite.plugins.context", "gateway"),  # ctx.register_platform()
    ("clite.cron.scheduler", "runtime"),  # a job runs through runtime.factory.build_agent
}


def _area(module: str) -> str:
    parts = module.split(".")
    if len(parts) == 1:
        return "(root)"
    if parts[1] == "plugins" and len(parts) > 2 and parts[2] == "hooks":
        return "plugins.hooks"
    return parts[1]


def _module_name(path: Path) -> str:
    return ".".join(("clite", *path.relative_to(PACKAGE).with_suffix("").parts)).removesuffix(".__init__")


def _internal_imports(path: Path) -> list[tuple[str, bool, int]]:
    """``(imported module, is_lazy, line)`` for every ``clite`` import that runs at runtime.

    ``if TYPE_CHECKING:`` blocks are skipped: they never execute.
    """
    found: list[tuple[str, bool, int]] = []

    def visit(node: ast.AST, lazy: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.If) and isinstance(child.test, ast.Name) and child.test.id == "TYPE_CHECKING":
                continue
            names: list[str] = []
            if isinstance(child, ast.Import):
                names = [alias.name for alias in child.names]
            elif isinstance(child, ast.ImportFrom) and child.module and child.level == 0:
                names = [child.module]
            found.extend((name, lazy, child.lineno) for name in names if name == "clite" or name.startswith("clite."))
            visit(child, lazy or isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef))

    visit(ast.parse(path.read_text(encoding="utf-8")), False)
    return found


def _source_files() -> list[Path]:
    return [path for path in sorted(PACKAGE.rglob("*.py")) if "bundled" not in path.parts]


def test_every_package_has_a_layer():
    areas = {_area(_module_name(path)) for path in _source_files()}
    assert areas <= set(LAYER_RANK), f"add a rank for: {sorted(areas - set(LAYER_RANK))}"


def test_imports_point_down_the_layers():
    violations = []
    used_exceptions = set()
    for path in _source_files():
        module = _module_name(path)
        source = _area(module)
        for imported, lazy, line in _internal_imports(path):
            target = _area(imported)
            if target == source or LAYER_RANK[target] < LAYER_RANK[source]:
                continue
            if lazy and (module, target) in ALLOWED_UPWARD_LAZY_IMPORTS:
                used_exceptions.add((module, target))
                continue
            kind = "inside a function" if lazy else "at module level"
            violations.append(f"{path.relative_to(REPO_ROOT)}:{line}: {source} imports {imported} ({target}) {kind}")
    assert not violations, (
        "imports must point down the layers (see LAYER_RANK in this file):\n  " + "\n  ".join(violations)
    )
    stale = ALLOWED_UPWARD_LAZY_IMPORTS - used_exceptions
    assert not stale, f"these exceptions are no longer used; remove them: {sorted(stale)}"


def test_core_imports_nothing_from_the_rest_of_the_package():
    for path in sorted((PACKAGE / "core").rglob("*.py")):
        outside = [name for name, _, _ in _internal_imports(path) if _area(name) not in ("core", "(root)")]
        assert not outside, f"{path.name} imports {outside}; core must stay a leaf"


def test_bundled_plugins_use_only_the_plugin_api():
    """A bundled plugin is the example third-party authors copy. It may import what any plugin
    may: ``core``, the provider profile API and the hook bus. Everything else reaches a plugin
    through the ``ctx`` it is handed, never through an import of the agent's internals."""
    allowed = ("clite.core.", "clite.providers.base", "clite.providers.registry", "clite.providers.transports",
               "clite.plugins.hooks")
    for path in sorted((PACKAGE / "bundled").rglob("*.py")):
        for name, _, line in _internal_imports(path):
            assert name.startswith(allowed), f"{path.relative_to(REPO_ROOT)}:{line} imports {name}"


# ── configuration ────────────────────────────────────────────────────────────────────────

# A key is "read" when its full dotted path appears as a string in the source. Keys that are
# read another way are listed here with the file and the code that reads them, and the test
# checks that code is still there.
READ_INDIRECTLY: dict[str, tuple[str, str]] = {
    "model.default": ("providers/runtime.py", 'section.get("default")'),
    "model.base_url": ("providers/runtime.py", 'section.get("base_url")'),
    "model.api_mode": ("providers/runtime.py", 'section.get("api_mode")'),
    "auxiliary.compression.provider": ("providers/auxiliary.py", 'f"auxiliary.{task}.provider"'),
    "auxiliary.compression.model": ("providers/auxiliary.py", 'f"auxiliary.{task}.model"'),
    "auxiliary.title_generation.provider": ("agent/title.py", '"title_generation"'),
    "auxiliary.title_generation.model": ("agent/title.py", '"title_generation"'),
    "auxiliary.approval.provider": ("tools/approval.py", '"approval", [{"role": "user"'),
    "auxiliary.approval.model": ("tools/approval.py", '"approval", [{"role": "user"'),
    "skills.external_dirs": ("skills/catalog.py", '.get("external_dirs")'),
    "skills.disabled": ("skills/catalog.py", '.get("disabled")'),
    "plugins.entries": ("plugins/context.py", 'f"plugins.entries.{self.plugin_id}.settings"'),
    "hooks": ("plugins/shell_hooks.py", '.get("hooks")'),
}


def _leaf_keys(node: dict, prefix: str = "") -> list[str]:
    keys: list[str] = []
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict) and value:
            keys.extend(_leaf_keys(value, path))
        else:
            keys.append(path)
    return keys


def test_every_config_key_has_a_reader():
    sources = {
        path: path.read_text(encoding="utf-8")
        for path in sorted(PACKAGE.rglob("*.py")) if path.name != "config_defaults.py"
    }
    everything = "\n".join(sources.values())
    unread = []
    for key in _leaf_keys(DEFAULT_CONFIG):
        if f'"{key}"' in everything or f"'{key}'" in everything:
            continue
        if key in READ_INDIRECTLY:
            relative, snippet = READ_INDIRECTLY[key]
            assert snippet in (PACKAGE / relative).read_text(encoding="utf-8"), (
                f"{key}: the reader recorded in READ_INDIRECTLY is gone from {relative} ({snippet})"
            )
            continue
        unread.append(key)
    assert not unread, (
        "these DEFAULT_CONFIG keys are read nowhere; a setting nothing reads is a knob that does "
        f"nothing. Implement a reader or delete the key: {unread}"
    )


def test_indirect_reader_table_has_no_stale_entries():
    keys = set(_leaf_keys(DEFAULT_CONFIG))
    assert set(READ_INDIRECTLY) <= keys, f"not config keys any more: {sorted(set(READ_INDIRECTLY) - keys)}"


# ── generated code ───────────────────────────────────────────────────────────────────────


def test_typescript_contracts_match_the_python_contracts():
    script = REPO_ROOT / "scripts" / "gen_rpc_contracts.py"
    if not script.is_file():
        pytest.skip("not a source checkout")
    result = subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True, timeout=120,
                            cwd=REPO_ROOT, env=_env_with_source_path())
    assert result.returncode == 0, (
        "apps/shared/src/contracts.generated.ts is out of date. Run `python scripts/gen_rpc_contracts.py`.\n"
        + result.stdout + result.stderr
    )


def test_generated_reference_pages_are_current():
    script = REPO_ROOT / "scripts" / "gen_docs.py"
    if not script.is_file():
        pytest.skip("not a source checkout")
    result = subprocess.run([sys.executable, str(script), "--check"], capture_output=True, text=True, timeout=120,
                            cwd=REPO_ROOT, env=_env_with_source_path())
    assert result.returncode == 0, (
        "docs/referensi/ is out of date (a tool, command, RPC method, config key or module changed). "
        "Run `python scripts/gen_docs.py` and commit the result.\n" + result.stdout + result.stderr
    )


def _env_with_source_path() -> dict[str, str]:
    import os

    path = os.pathsep.join(filter(None, [str(REPO_ROOT / "src"), os.environ.get("PYTHONPATH", "")]))
    return {**os.environ, "PYTHONPATH": path}
