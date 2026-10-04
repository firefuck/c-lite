#!/usr/bin/env python3
"""Rename the project: package, CLI command, home directory, environment prefix, display name.

    python scripts/rename_project.py --name orbit --display "Orbit" --dry-run
    python scripts/rename_project.py --name orbit --display "Orbit"

The current names are read from the repository itself (``APP_NAME`` and ``DISPLAY_NAME`` in
``src/<package>/core/brand.py``), so the script works again after a rename. With the current
package name written as ``old`` and the new one as ``new``:

    old         -> new          package ``src/old``, the command, ``~/.old``, file names
    OLD         -> NEW          environment variables (``OLD_HOME`` -> ``NEW_HOME``)
    Old         -> New          inside identifiers (``OldError`` -> ``NewError``)
    <display>   -> --display    the name people read, where it stands as a word of its own
    extra console scripts       dropped, or renamed with ``--alias``

The script edits text files in place and renames files and directories. Run it on a clean
git tree: ``git diff`` then shows exactly what it did and ``git checkout . && git clean -fd``
undoes it. Afterwards regenerate the generated files (the script prints the commands) and
run the tests; they are what proves the rename left the tree consistent.

It is deliberately simple: string replacement, no parsing. That works because the code never
spells the name any other way, and ``core/brand.py`` is where code reads the name from.
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {".git", "node_modules", "dist", "build", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
             ".venv", "venv"}
SKIP_SUFFIXES = {".pyc", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".icns", ".woff", ".woff2", ".db", ".gz", ".zip", ".whl"}
VALID_NAME = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
WORD = r"[A-Za-z0-9_]"


class RenameError(Exception):
    pass


def current_brand(root: Path) -> tuple[str, str, list[str]]:
    """``(package name, display name, extra console scripts)`` as the repository states them."""
    brand_files = sorted((root / "src").glob("*/core/brand.py"))
    if len(brand_files) != 1:
        raise RenameError(f"expected exactly one src/<package>/core/brand.py under {root}, found {len(brand_files)}")
    text = brand_files[0].read_text(encoding="utf-8")
    name = re.search(r'^APP_NAME = "([^"]+)"', text, re.MULTILINE)
    display = re.search(r'^DISPLAY_NAME = "([^"]+)"', text, re.MULTILINE)
    if not name or not display:
        raise RenameError(f"{brand_files[0]} does not define APP_NAME and DISPLAY_NAME as plain strings")
    scripts = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")).get("project", {}).get("scripts", {})
    return name.group(1), display.group(1), [key for key in scripts if key != name.group(1)]


def build_rewriter(old: str, old_display: str, new: str, new_display: str, aliases: dict[str, str]):
    """A function that rewrites one text. Rules run in this order:

    1. the display name, only where it is a word of its own (never inside an identifier);
    2. console-script aliases that are kept;
    3. OLD, Old, old inside anything.
    """
    standalone_display = re.compile(rf"(?<!{WORD}){re.escape(old_display)}(?!{WORD})")
    plain = [(old.upper(), new.upper()), (old.capitalize(), new.capitalize()), (old, new)]

    def rewrite(text: str) -> str:
        text = standalone_display.sub(lambda _match: new_display, text)
        for alias, replacement in aliases.items():
            text = text.replace(alias, replacement)
        for before, after in plain:
            text = text.replace(before, after)
        return text

    return rewrite


def drop_console_scripts(text: str, names: list[str]) -> str:
    """Remove ``name = "..."`` lines from pyproject.toml for console scripts that are not kept."""
    for name in names:
        text = re.sub(rf'^"?{re.escape(name)}"?[ \t]*=[ \t]*".*"[ \t]*\n', "", text, flags=re.MULTILINE)
    return text


def is_skipped(relative: Path) -> bool:
    return (bool(SKIP_DIRS.intersection(relative.parts)) or relative.suffix.lower() in SKIP_SUFFIXES
            or any(part.endswith(".egg-info") for part in relative.parts))


def text_files(root: Path) -> list[Path]:
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file() or is_skipped(path.relative_to(root)):
            continue
        try:
            path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        files.append(path)
    return files


def rename_paths(root: Path, old: str, new: str, *, dry_run: bool) -> list[tuple[Path, Path]]:
    """Rename every file and directory whose own name contains the old name, deepest first."""
    candidates = [path for path in root.rglob("*") if old in path.name and not is_skipped(path.relative_to(root))]
    moves = []
    for path in sorted(candidates, key=lambda item: len(item.parts), reverse=True):
        target = path.with_name(path.name.replace(old, new))
        moves.append((path, target))
        if not dry_run:
            path.rename(target)
    return moves


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Rename the project everywhere in this repository.")
    parser.add_argument("--name", required=True, help="new package and command name: lowercase letters, digits, underscore")
    parser.add_argument("--display", required=True, help="new display name, e.g. 'Orbit'")
    parser.add_argument("--alias", help="keep one extra console script under this name (default: extra scripts are dropped)")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository to rename (default: this one)")
    parser.add_argument("--dry-run", action="store_true", help="show what would change and change nothing")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    try:
        old, old_display, old_aliases = current_brand(root)
    except RenameError as exc:
        parser.error(str(exc))
    if not VALID_NAME.match(args.name):
        parser.error("--name must be lowercase letters, digits and underscores, starting with a letter")
    if args.name == old:
        parser.error("that is already the name")
    if old in args.name or old in args.display.lower():
        parser.error(f"the new names must not contain {old!r}: the replacement could not be told apart from the original")

    kept = {old_aliases[0]: args.alias} if args.alias and old_aliases else {}
    dropped = [alias for alias in old_aliases if alias not in kept]
    rewrite = build_rewriter(old, old_display, args.name, args.display, kept)

    print(f"{old!r} ({old_display!r}) -> {args.name!r} ({args.display!r})")
    edited = 0
    for path in text_files(root):
        original = path.read_text(encoding="utf-8")
        updated = drop_console_scripts(original, dropped) if path.name == "pyproject.toml" else original
        updated = rewrite(updated)
        if updated == original:
            continue
        edited += 1
        if args.dry_run:
            print(f"would edit   {path.relative_to(root)}")
        else:
            path.write_text(updated, encoding="utf-8")
    moves = rename_paths(root, old, args.name, dry_run=args.dry_run)
    for source, target in moves:
        print(f"{'would move' if args.dry_run else 'moved'}   {source.relative_to(root)} -> {target.name}")

    verb = "would be" if args.dry_run else "were"
    print(f"\n{edited} file(s) {verb} edited, {len(moves)} path(s) {verb} renamed.")
    if not args.dry_run:
        print(
            "\nNext:\n"
            "  1. python scripts/gen_rpc_contracts.py     regenerate the TypeScript contracts\n"
            "  2. (cd ui-tui && npm run build)            rebuild the terminal UI shipped in the package\n"
            "  3. pip install -e '.[dev]'                 the package directory changed\n"
            "  4. scripts/run_tests.sh\n"
            f"  5. Existing installs: move ~/.{old} to ~/.{args.name} and rename {old.upper()}_* variables."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
