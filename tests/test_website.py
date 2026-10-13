"""The user documentation site: the pages, the generator, and the examples they promise.

The site is what a reader who never opens the code sees, so the tests here are about the
promises it makes rather than about the renderer's internals: that the reference pages cannot
drift from the code, that both language trees hold the same pages, and that the commands the
quick start tells you to run really do run.

Nothing here touches the network. The quick start is executed against the ``mock`` provider, in
the throwaway home the ``clite_home`` fixture provides.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CONTENT = REPO_ROOT / "website" / "content"
LANGUAGES = ("id", "en")
QUICKSTART = "start/quickstart.md"

# `clite` commands the quick start shows in a `console` transcript, with why the suite does not
# run them. Anything shown and neither run nor listed here fails the test below, so the page
# cannot quietly gain a command nobody executes.
NOT_EXECUTED: dict[str, str] = {
    "clite": "opens the interactive REPL, which waits for input",
    "clite setup": "asks its questions on a terminal; the flag form is the one that is run",
    'clite setup --provider openrouter --api-key "$OPENROUTER_KEY" --model anthropic/claude-sonnet-5': (
        "needs a real API key and a network call to the provider"
    ),
}


def _env() -> dict[str, str]:
    path = os.pathsep.join(filter(None, [str(REPO_ROOT / "src"), os.environ.get("PYTHONPATH", "")]))
    return {**os.environ, "PYTHONPATH": path, "NO_COLOR": "1"}


def _pages(language: str) -> list[str]:
    """Every page of one language tree, as slugs like ``guide/tools.md``."""
    root = CONTENT / language
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*.md"))


def _read(language: str, page: str) -> str:
    return (CONTENT / language / page).read_text(encoding="utf-8")


def _fences(markdown: str) -> list[tuple[str, list[str]]]:
    """``(info string, lines)`` for every fenced block of a page, in order."""
    fences: list[tuple[str, list[str]]] = []
    info: str | None = None
    lines: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if info is None:
            if stripped.startswith("```"):
                info = stripped[3:].strip()
                lines = []
            continue
        if stripped.startswith("```"):
            fences.append((info, lines))
            info = None
            continue
        lines.append(line)
    assert info is None, "a code fence is never closed"
    return fences


def _blocks(markdown: str, info: str) -> list[list[str]]:
    return [lines for kind, lines in _fences(markdown) if kind == info]


def _commands(block: list[str]) -> list[str]:
    return [line.strip() for line in block if line.strip() and not line.strip().startswith("#")]


def _shape(command: str) -> str:
    """The part of a runnable example that must read the same in both languages: the program,
    the subcommand, and the flags. The sample text a user types is prose, so it is masked."""
    return re.sub(r'"[^"]*"', '"<text>"', command)


def _runnable(language: str) -> list[str]:
    """Every line of every ```bash block of that language's quick start, in order."""
    return [command for block in _blocks(_read(language, QUICKSTART), "bash") for command in _commands(block)]


def _shape(markdown: str) -> tuple[int, list[str], int]:
    """The parts of a page that must survive translation: how many headings it has, the code
    fences it opens in order, and how many table rows it shows."""
    lines = markdown.splitlines()
    return (
        sum(1 for line in lines if line.startswith("#")),
        [info for info, _lines in _fences(markdown)],
        sum(1 for line in lines if line.strip().startswith("|")),
    )


@pytest.fixture(scope="module")
def builder() -> Any:
    """``scripts/build_site.py`` as a module, so the tests use the real navigation and renderer."""
    spec = importlib.util.spec_from_file_location(
        "build_site_under_test", REPO_ROOT / "scripts" / "build_site.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── the reference pages come from the code ───────────────────────────────────────────────


def test_the_reference_pages_of_the_site_match_the_generator():
    """F6-T9: the user reference is generated from the live registries, so it cannot fall
    behind the code it describes."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "gen_docs.py"), "--target", "site", "--check"],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=REPO_ROOT,
        env=_env(),
    )
    assert result.returncode == 0, (
        "website/content/*/reference/ is out of date (a tool, command, provider or config key "
        "changed). Run `python scripts/gen_docs.py --target site` and commit the result.\n"
        + result.stdout
        + result.stderr
    )


def test_the_generated_pages_are_the_only_ones_in_the_reference_tree():
    """A hand-written page in `reference/` would be overwritten by the next generator run."""
    generated = {"reference/commands.md", "reference/config.md", "reference/tools.md"}
    for language in LANGUAGES:
        in_tree = {page for page in _pages(language) if page.startswith("reference/")}
        assert in_tree == generated, (
            f"{language}: unexpected page in the generated tree: {in_tree - generated}"
        )


# ── both languages are complete ──────────────────────────────────────────────────────────


def test_both_language_trees_hold_the_same_pages():
    """The language switcher maps a page to the same slug in the other tree, so the two trees
    must hold exactly the same slugs."""
    assert _pages("id"), "the site has no pages"
    assert _pages("id") == _pages("en")


def test_every_page_is_reachable_from_the_menu(builder: Any):
    """A page the navigation does not list cannot be reached by a reader at all."""
    listed = {f"{slug}.md" for slug in builder.slugs()}
    assert listed == set(_pages("id")), "the navigation and the content tree disagree"


def test_every_page_starts_with_one_top_level_heading():
    """The menu label is the page's own H1, so the menu and the page cannot drift apart."""
    for language in LANGUAGES:
        for page in _pages(language):
            assert _read(language, page).startswith("# "), f"{language}/{page} has no '# ' heading"


def test_translation_keeps_the_shape_of_the_page():
    """Only the prose changes between the two trees: the same sections, the same code blocks in
    the same order, and the same table rows. A translation that drops a command or a row would
    otherwise pass every other test here."""
    for page in _pages("id"):
        indonesian = _shape(_read("id", page))
        english = _shape(_read("en", page))
        assert indonesian == english, f"en/{page} does not have the shape of id/{page}"


# ── the site builds ──────────────────────────────────────────────────────────────────────


def test_the_site_builds_and_writes_every_page(builder: Any, tmp_path: Path):
    out = tmp_path / "site"
    builder.build(out)
    for language in LANGUAGES:
        for page in _pages(language):
            target = out / language / page.replace(".md", ".html")
            assert target.is_file(), f"{language}/{page} was not built"
    assert (out / "index.html").is_file(), "the landing page is missing"
    assert (out / "style.css").is_file(), "the stylesheet was not copied to the root of the build"


def test_the_language_switcher_points_at_the_same_page(builder: Any, tmp_path: Path):
    out = tmp_path / "site"
    builder.build(out)
    for language in LANGUAGES:
        other = "en" if language == "id" else "id"
        for page in _pages(language):
            up = "../" * (1 + page.count("/"))
            html = (out / language / page.replace(".md", ".html")).read_text(encoding="utf-8")
            assert f'href="{up}{other}/{page.replace(".md", ".html")}"' in html, (
                f"{language}/{page} does not link to its {other} counterpart"
            )


def test_every_relative_link_in_the_built_pages_resolves(tmp_path: Path, builder: Any):
    """The generator rewrites `.md` to `.html`; a link that survives that rewriting but points
    at no built file would 404 on the published site."""
    out = tmp_path / "site"
    builder.build(out)
    link = re.compile(r'href="([^"#]+)')
    for language in LANGUAGES:
        for page in _pages(language):
            target = out / language / page.replace(".md", ".html")
            for href in link.findall(target.read_text(encoding="utf-8")):
                if href.startswith(("http://", "https://", "mailto:")):
                    continue
                assert (target.parent / href).resolve().exists(), (
                    f"{language}/{page} links to {href}, which is not in the build"
                )


# ── the examples are real ────────────────────────────────────────────────────────────────


def test_only_the_quick_start_runs_its_examples():
    """A ```bash block is executed by the suite below, so it may only appear where the page
    says so. Everywhere else the fence is `console` (a transcript, read but not run)."""
    offenders = [
        f"{language}/{page}"
        for language in LANGUAGES
        for page in _pages(language)
        if page != QUICKSTART and _blocks(_read(language, page), "bash")
    ]
    assert not offenders, f"a ```bash block is executed by the tests; keep it to the quick start: {offenders}"


def test_both_languages_run_the_same_commands():
    """An English reader and an Indonesian reader are told to run the same thing; only the
    sample text they type differs (a prompt, a file name — prose, written in the page's own
    language)."""
    indonesian = [_shape(command) for command in _runnable("id")]
    assert indonesian, "the quick start shows no runnable example"
    assert indonesian == [_shape(command) for command in _runnable("en")]


def test_the_commands_in_the_quick_start_run_as_written(clite_home: Path):
    """F6-T9: every line in every ```bash block of the quick start is run here, in both
    languages, against the `mock` provider, so the page cannot tell the reader to run something
    that does not work."""
    # `doctor` reports a missing provider until one is configured, and a script cannot answer
    # `setup`'s questions. That is what a fresh install looks like.
    (clite_home / "config.yaml").write_text("model:\n  provider: mock\n  default: mock-1\n", encoding="utf-8")
    for language in LANGUAGES:
        for command in _runnable(language):
            parts = shlex.split(command)
            assert parts and parts[0] == "clite", f"an example must be a `clite` command: {command!r}"
            result = subprocess.run(
                [sys.executable, "-m", "clite", *parts[1:]],
                capture_output=True,
                text=True,
                timeout=180,
                cwd=clite_home.parent,
                env=_env(),
            )
            assert result.returncode == 0, (
                f"the {language} quick start shows `{command}`, and it fails:\n"
                + result.stdout
                + result.stderr
            )


def test_every_command_the_quick_start_shows_is_either_run_or_explained():
    """A command shown in a transcript but never executed is a promise nobody checked. Either
    it is in a ```bash block, or it is in NOT_EXECUTED with a reason."""
    markdown = _read("id", QUICKSTART)
    executed = {line for block in _blocks(markdown, "bash") for line in _commands(block)}
    shown = [
        command
        for block in _blocks(markdown, "console")
        for line in block
        if (command := re.sub(r"^\$\s+", "", line.strip())) in executed
        or (command.startswith("clite") and command)
    ]
    unexplained = [command for command in shown if command not in executed and command not in NOT_EXECUTED]
    assert not unexplained, (
        "the quick start shows commands the suite neither runs nor explains:\n  " + "\n  ".join(unexplained)
    )
