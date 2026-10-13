"""The dashboard as shipped: the bundle inside the Python package.

``clite dashboard`` serves ``src/clite/server/static/``, which is built from TypeScript in
``web/`` and ``apps/shared/``. These tests check that the committed bundle matches its sources
and that it is self-contained.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

from clite.server.app import STATIC_DIR

REPO_ROOT = Path(__file__).resolve().parents[2]
# Keep in sync with SOURCE_DIRS, SOURCE_FILES and EXTENSIONS in web/build.mjs.
BUNDLE_SOURCE_DIRS = ("apps/shared/src", "web/src")
BUNDLE_SOURCE_FILES = ("web/index.html",)
BUNDLE_EXTENSIONS = (".ts", ".tsx", ".css")


def source_hash() -> str:
    """The same hash web/build.mjs records: sorted relative paths and file contents."""
    paths = [
        path
        for directory in BUNDLE_SOURCE_DIRS
        for path in (REPO_ROOT / directory).rglob("*")
        if path.suffix in BUNDLE_EXTENSIONS
    ] + [REPO_ROOT / name for name in BUNDLE_SOURCE_FILES]
    digest = hashlib.sha256()
    for name, path in sorted((path.relative_to(REPO_ROOT).as_posix(), path) for path in paths):
        digest.update(name.encode() + b"\0")
        digest.update(path.read_text(encoding="utf-8").replace("\r\n", "\n").encode() + b"\0")
    return digest.hexdigest()


def test_the_bundle_ships_inside_the_package():
    for name in ("index.html", "build-info.json", "assets/app.js", "assets/app.css"):
        assert (STATIC_DIR / name).is_file(), name


def test_the_committed_bundle_was_built_from_the_current_sources():
    if not (REPO_ROOT / "web" / "src").is_dir():
        pytest.skip("not a source checkout")
    recorded = json.loads((STATIC_DIR / "build-info.json").read_text())["source_hash"]
    assert recorded == source_hash(), (
        "web/src, web/index.html or apps/shared/src changed after the dashboard was built. "
        "Run `npm run build` in web/ and commit src/clite/server/static/."
    )


def test_the_page_loads_only_its_own_bundle():
    """No CDN, no module fetched at runtime: the page works offline and on a locked-down host."""
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    sources = re.findall(r'(?:src|href)="([^"]+)"', html)
    assert sources and all(source.startswith("/assets/") for source in sources), sources
    script = (STATIC_DIR / "assets" / "app.js").read_text(encoding="utf-8")
    assert not re.search(r"""\bimport\s*\(?\s*["']https?://""", script)


def test_the_bundle_never_sets_html_from_data():
    """Text from the model or a tool is text: the dashboard never hands React raw HTML."""
    sources = "\n".join(
        path.read_text(encoding="utf-8") for path in (REPO_ROOT / "web" / "src").rglob("*.tsx")
    )
    if not sources:
        pytest.skip("not a source checkout")
    assert "dangerouslySetInnerHTML" not in sources
    assert ".innerHTML" not in sources
