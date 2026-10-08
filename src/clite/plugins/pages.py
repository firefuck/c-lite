"""The dashboard page a plugin ships, and the files around it.

A plugin may declare a page in its manifest::

    dashboard:
      title: Deploy board
      page: dashboard/index.html

The page is served by the backend from **its own origin** — a second loopback listener on its
own port, started only when a loaded plugin has a page. That is the whole point of the
sub-step: a plugin's HTML/JS runs in a frame that shares nothing with the dashboard. It cannot
read the dashboard's DOM, its ``sessionStorage`` or the session token, and the WebSocket
handshake it would need to reach the backend is refused by the origin check
(``clite.server.app.origin_allowed``): its origin is a different port, and a browser sends that
origin, so the check sees a page from another site.

What a page *can* do is read the plugin's own files. ``resolve_asset`` is the only way to turn
a URL path into a file, and it refuses anything that leaves the plugin directory, any dotfile
and any suffix that is not a web asset.

Opt-in still governs: only a plugin that is **loaded** has a page.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from clite.plugins.manager import get_plugin_manager

# Suffixes the page listener will hand out. Everything else is a 404, so a plugin's source
# files, its manifest and any secret it keeps next to them stay out of the browser.
ASSET_SUFFIXES = frozenset(
    {".html", ".css", ".js", ".mjs", ".json", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".woff2"}
)

_ORIGIN_LOCK = threading.Lock()
_ORIGIN = ""  # http://127.0.0.1:<port> of the page listener, "" when it is not running


def set_plugin_origin(origin: str) -> None:
    """Record where the page listener is reachable. Called by ``clite.server.run``."""
    global _ORIGIN
    with _ORIGIN_LOCK:
        _ORIGIN = (origin or "").rstrip("/")


def plugin_origin() -> str:
    with _ORIGIN_LOCK:
        return _ORIGIN


@dataclass(frozen=True)
class DashboardPage:
    plugin: str
    title: str
    directory: Path  # the plugin's own directory: the root the page may read
    entry: str  # path of the page file inside it

    @property
    def url_path(self) -> str:
        """The page's path on the plugin origin. Plugin names are ``[a-z0-9_-]``, so it needs
        no escaping."""
        return f"/{self.plugin}/{self.entry}"

    def url(self) -> str:
        """The absolute URL to put in a frame, or ``""`` when the listener is not running."""
        origin = plugin_origin()
        return f"{origin}{self.url_path}" if origin else ""


def dashboard_pages() -> list[DashboardPage]:
    """The pages of the plugins loaded right now, in plugin order."""
    pages: list[DashboardPage] = []
    for info in get_plugin_manager().list():
        manifest = info.manifest
        if info.status != "loaded" or info.path is None or not manifest.dashboard_page:
            continue
        pages.append(
            DashboardPage(
                plugin=info.name,
                title=manifest.dashboard_title or info.name,
                directory=Path(info.path),
                entry=manifest.dashboard_page,
            )
        )
    return pages


def find_page(plugin: str) -> DashboardPage | None:
    return next((page for page in dashboard_pages() if page.plugin == plugin), None)


def resolve_asset(page: DashboardPage, relative: str = "") -> Path | None:
    """The file ``relative`` names inside the page's directory, or ``None`` when it is not one.

    ``""`` means the page's own entry. A path that climbs out of the directory (``..``), a
    symlink pointing outside it, a dotfile, and a suffix that is not a web asset are all
    ``None`` — the caller answers 404 without saying which of them it was.
    """
    relative = (relative or "").replace("\\", "/").strip("/")
    parts = PurePosixPath(relative).parts if relative else ()
    if any(part.startswith(".") or part == ".." for part in parts):
        return None
    try:
        root = page.directory.resolve()
        candidate = (page.directory / (relative or page.entry)).resolve()
    except OSError:
        return None
    if candidate == root or not candidate.is_relative_to(root) or not candidate.is_file():
        return None
    if candidate.suffix.lower() not in ASSET_SUFFIXES:
        return None
    return candidate


def reset_plugin_origin() -> None:
    set_plugin_origin("")
