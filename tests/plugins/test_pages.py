"""Plugin dashboard pages: what the manifest accepts and which files the listener will serve."""

from __future__ import annotations

import pytest

from clite.plugins.manager import ensure_plugins_loaded
from clite.plugins.manifest import ManifestError, parse_manifest
from clite.plugins.pages import (
    dashboard_pages,
    find_page,
    plugin_origin,
    reset_plugin_origin,
    resolve_asset,
    set_plugin_origin,
)


def _write_plugin(root, name, *, manifest="", page=False):
    directory = root / name
    directory.mkdir(parents=True)
    (directory / "plugin.yaml").write_text(f"name: {name}\n{manifest}")
    (directory / "__init__.py").write_text("def register(ctx):\n    pass\n")
    if page:
        (directory / "dashboard").mkdir()
        (directory / "dashboard" / "index.html").write_text("<h1>board</h1>")
        (directory / "dashboard" / "app.js").write_text("console.log('board');")
        (directory / "secrets.env").write_text("TOKEN=leak-me")
    return directory


def _enable(home, *names):
    (home / "config.yaml").write_text("plugins:\n  enabled: [" + ", ".join(names) + "]\n")


PAGE = "dashboard:\n  title: Deploy board\n  page: dashboard/index.html\n"


@pytest.fixture
def plugins_dir(clite_home):
    return clite_home / "plugins"


def test_a_manifest_may_declare_a_dashboard_page():
    manifest = parse_manifest(
        {"name": "board", "dashboard": {"title": "Deploy board", "page": "d/index.html"}}
    )
    assert (manifest.dashboard_title, manifest.dashboard_page) == ("Deploy board", "d/index.html")
    # A bare string is the page, and the title falls back to the plugin's name.
    shorthand = parse_manifest({"name": "board", "dashboard": "d/index.html"})
    assert (shorthand.dashboard_title, shorthand.dashboard_page) == ("board", "d/index.html")
    assert parse_manifest({"name": "board"}).dashboard_page == ""  # no page is the normal case


@pytest.mark.parametrize(
    "value",
    [
        {"page": "../outside.html"},  # climbs out of the plugin
        {"page": "/etc/passwd.html"},  # absolute
        {"page": "dashboard/index.htmlx"},  # not an HTML file
        {"page": ""},  # declared but empty
        {"title": "no page"},  # a mapping with no page at all
        42,
    ],
)
def test_a_dashboard_page_must_be_an_html_file_inside_the_plugin(value):
    with pytest.raises(ManifestError):
        parse_manifest({"name": "board", "dashboard": value})


def test_only_loaded_plugins_have_pages(plugins_dir, clite_home):
    _write_plugin(plugins_dir, "board", manifest=PAGE, page=True)
    _write_plugin(plugins_dir, "quiet", manifest="")
    ensure_plugins_loaded()
    assert dashboard_pages() == []  # opt-in first: nothing is enabled yet

    _enable(clite_home, "board")
    ensure_plugins_loaded().load_all()
    (page,) = dashboard_pages()
    assert (page.plugin, page.title, page.entry) == ("board", "Deploy board", "dashboard/index.html")
    assert page.url_path == "/board/dashboard/index.html"
    assert find_page("quiet") is None and find_page("nowhere") is None


def test_a_page_has_no_url_until_its_listener_is_running(plugins_dir, clite_home):
    _write_plugin(plugins_dir, "board", manifest=PAGE, page=True)
    _enable(clite_home, "board")
    ensure_plugins_loaded().load_all()
    page = dashboard_pages()[0]
    assert page.url() == ""
    set_plugin_origin("http://127.0.0.1:9999/")
    assert page.url() == "http://127.0.0.1:9999/board/dashboard/index.html"
    assert plugin_origin() == "http://127.0.0.1:9999"
    reset_plugin_origin()
    assert page.url() == ""


def test_a_page_serves_its_own_web_assets_and_nothing_else(plugins_dir, clite_home):
    _write_plugin(plugins_dir, "board", manifest=PAGE, page=True)
    _enable(clite_home, "board")
    ensure_plugins_loaded().load_all()
    page = dashboard_pages()[0]

    assert resolve_asset(page) == page.directory / "dashboard" / "index.html"  # "" is the entry
    assert resolve_asset(page, "dashboard/app.js") == page.directory / "dashboard" / "app.js"
    for refused in (
        "../secrets.env",  # out of the plugin
        "dashboard/../../secrets.env",
        "secrets.env",  # a file in the plugin, but not a web asset
        "plugin.yaml",
        "dashboard/.hidden.js",  # dotfile
        "dashboard/missing.js",
        "",  # the entry, but the file is gone
    ):
        if refused == "":
            (page.directory / "dashboard" / "index.html").unlink()
        assert resolve_asset(page, refused) is None, refused


def test_a_symlink_out_of_the_plugin_directory_is_not_served(plugins_dir, clite_home, tmp_path):
    _write_plugin(plugins_dir, "board", manifest=PAGE, page=True)
    _enable(clite_home, "board")
    ensure_plugins_loaded().load_all()
    page = dashboard_pages()[0]
    outside = tmp_path / "elsewhere.js"
    outside.write_text("alert('outside');")
    (page.directory / "dashboard" / "linked.js").symlink_to(outside)

    assert resolve_asset(page, "dashboard/linked.js") is None
    assert outside.read_text() == "alert('outside');"
