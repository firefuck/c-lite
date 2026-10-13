"""The plugin hub: provenance, the catalog, search, and updates."""

from __future__ import annotations

import json

import pytest

from clite.core.config import config_set
from clite.plugins.hub import (
    PluginError,
    apply_update,
    build_index,
    dependency_commands,
    index_locations,
    installed_plugins,
    plan_update,
    plugin_digest,
    search_plugins,
)
from clite.plugins.manager import get_plugin_manager, install_plugin, remove_plugin
from clite.plugins.manifest import parse_manifest

BODY = "def register(ctx):\n    ctx.register_command('{name}', lambda args, session=None: 'hi')\n"


def _write_plugin(root, name, *, version="1.0.0", kind="standalone", body=None, extra=""):
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "plugin.yaml").write_text(
        f"name: {name}\nversion: {version}\nkind: {kind}\ndescription: {name} does a thing\n{extra}"
        "author: nobody\n"
    )
    (directory / "__init__.py").write_text(body or BODY.format(name=name))
    return directory


@pytest.fixture
def plugins_dir(clite_home):
    return clite_home / "plugins"


@pytest.fixture
def hub_repo(tmp_path, plugins_dir):
    """A directory of plugins with a catalog that points at them as a local source."""
    root = tmp_path / "catalog"
    _write_plugin(root, "greeter", extra="pip_dependencies: [requests]\n")
    _write_plugin(root, "counter")
    index = tmp_path / "plugins-index.json"
    index.write_text(json.dumps(build_index(root, source="local")), encoding="utf-8")
    config_set("plugins.hub.index", str(index))
    return {"root": root, "index": index, "greeter": root / "greeter"}


# ── the catalog ──────────────────────────────────────────────────────────────────────────


def test_build_index_describes_every_plugin_with_a_hash(tmp_path):
    root = tmp_path / "catalog"
    _write_plugin(root, "greeter", kind="backend")
    _write_plugin(root, "other")
    document = build_index(root, source="local")
    assert document["version"] == 1
    by_name = {entry["name"]: entry for entry in document["plugins"]}
    assert set(by_name) == {"greeter", "other"}
    assert by_name["greeter"]["kind"] == "backend"
    assert by_name["greeter"]["hash"] == plugin_digest(root / "greeter")


def test_build_index_ignores_reserved_directories(tmp_path):
    root = tmp_path / "catalog"
    _write_plugin(root, "greeter")
    (root / "model-providers" / "acme").mkdir(parents=True)
    (root / "model-providers" / "acme" / "plugin.yaml").write_text("name: acme\n")
    assert [entry["name"] for entry in build_index(root)["plugins"]] == ["greeter"]


def test_build_index_refuses_two_plugins_with_the_same_name(tmp_path):
    root = tmp_path / "catalog"
    _write_plugin(root, "same")
    _write_plugin(root / "nested", "same")
    with pytest.raises(PluginError, match="duplicate names: same"):
        build_index(root)


def test_the_bundled_catalog_matches_the_bundled_plugins():
    """The committed catalog is what the script would write now."""
    from clite.plugins import hub

    root = hub.bundled_dir() / "plugins"
    rebuilt = build_index(
        root, source="github", identifier_prefix="dragovics/clite/src/clite/bundled/plugins"
    )
    committed = json.loads(hub.bundled_index_path().read_text(encoding="utf-8"))
    assert committed == rebuilt
    assert {entry["name"] for entry in committed["plugins"]} >= {"audit-log", "memory-sqlite"}


def test_search_matches_name_and_description(hub_repo):
    assert [entry["name"] for entry in search_plugins("greet").entries] == ["greeter"]
    assert [entry["name"] for entry in search_plugins("counter").entries] == ["counter"]
    assert search_plugins("nothing like this").entries == []


def test_a_catalog_that_cannot_be_read_is_reported_not_fatal(clite_home, tmp_path, monkeypatch):
    from clite.plugins import hub

    monkeypatch.setattr(hub, "bundled_index_path", lambda: tmp_path / "missing.json")
    results = search_plugins("")
    assert results.entries == [] and results.problems and "missing.json" in results.problems[0]


def test_index_locations_use_the_bundled_catalog_when_nothing_is_configured(clite_home):
    from clite.plugins.hub import bundled_index_path

    assert index_locations() == [str(bundled_index_path())]
    config_set("plugins.hub.index", "/tmp/other.json")
    assert index_locations() == ["/tmp/other.json"]


def test_a_configured_catalog_can_be_a_url(tmp_path, monkeypatch):
    from clite.plugins import hub

    server = _FakeIndexServer(json.dumps(build_index(tmp_path / "empty", source="local")))
    monkeypatch.setattr(hub, "bundled_index_path", lambda: tmp_path / "unused.json")
    try:
        config_set("plugins.hub.index", server.url)
        assert hub.read_index(server.url)["plugins"] == []
    finally:
        server.close()


class _FakeIndexServer:
    """The smallest HTTP server that answers one JSON document."""

    def __init__(self, body: str) -> None:
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        payload = body.encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # BaseHTTPRequestHandler's name
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/plugins-index.json"

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


# ── installing from a name, with provenance ──────────────────────────────────────────────


def test_install_from_the_catalog_records_where_it_came_from(hub_repo, plugins_dir):
    info = install_plugin("greeter")
    assert info.name == "greeter" and (plugins_dir / "greeter" / "plugin.yaml").is_file()
    record = installed_plugins()["greeter"]
    assert record["source"] == "local"
    assert record["identifier"] == str(hub_repo["greeter"])
    assert record["version"] == "1.0.0"
    assert record["hash"] == plugin_digest(plugins_dir / "greeter")
    assert record["installed_at"] > 0
    # Installing is not enabling, and the manager still says so.
    assert get_plugin_manager().discover()["greeter"].status == "not_enabled"


def test_install_from_a_name_that_is_not_in_the_catalog_lists_what_is(hub_repo, plugins_dir):
    with pytest.raises(PluginError, match="no plugin named 'nope' in the catalog"):
        install_plugin("nope")
    with pytest.raises(PluginError, match="Known plugins: counter, greeter"):
        install_plugin("nope")


def test_a_catalog_entry_whose_hash_does_not_match_is_refused(hub_repo, plugins_dir):
    document = json.loads(hub_repo["index"].read_text(encoding="utf-8"))
    document["plugins"][0]["hash"] = "sha256:" + "0" * 64
    hub_repo["index"].write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(PluginError, match="does not match the hash in the catalog"):
        install_plugin(document["plugins"][0]["name"])


def test_install_records_the_commit_of_a_git_source(tmp_path, plugins_dir):
    import subprocess

    source = _write_plugin(tmp_path / "checkout", "greeter")
    for command in (["git", "init", "-q"], ["git", "add", "-A"]):
        subprocess.run(command, cwd=source, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "first"],
        cwd=source,
        check=True,
        capture_output=True,
    )
    head = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True, check=True
    ).stdout.strip()
    install_plugin(str(source))
    assert installed_plugins()["greeter"]["commit"] == head


def test_pip_dependencies_become_a_command_for_the_user():
    manifest = parse_manifest({"name": "greeter", "pip_dependencies": ["requests", "rich>=13"]})
    assert dependency_commands(manifest) == ["pip install requests rich>=13"]
    assert dependency_commands(parse_manifest({"name": "greeter"})) == []


# ── updates ──────────────────────────────────────────────────────────────────────────────


def test_update_leaves_the_plugin_disabled_until_it_is_enabled_again(hub_repo, plugins_dir, clite_home):
    install_plugin("greeter")
    config_set("plugins.enabled", ["greeter"])
    manager = get_plugin_manager()
    manager.load_all()
    assert manager.plugins["greeter"].status == "loaded"

    (hub_repo["greeter"] / "__init__.py").write_text(
        "def register(ctx):\n    ctx.register_command('greeter', lambda args, session=None: 'new')\n"
    )
    hub_repo["index"].write_text(json.dumps(build_index(hub_repo["root"], source="local")), encoding="utf-8")
    plan = plan_update("greeter")
    assert plan.changed == {"__init__.py": "changed"}
    assert plan.summary() == "greeter: 1 changed"

    apply_update(plan)
    from clite.core.config import load_config

    assert "greeter" in load_config()["plugins"]["disabled"]
    assert "greeter" not in load_config()["plugins"]["enabled"]
    manager.load_all()
    assert manager.plugins["greeter"].status == "disabled"
    assert "greeter" not in manager.commands  # the updated code is not running


def test_an_update_among_several_files_reports_each_one(hub_repo, plugins_dir):
    install_plugin("greeter")
    source = hub_repo["greeter"]
    (source / "extra.py").write_text("VALUE = 1\n")
    (source / "__init__.py").unlink()
    (source / "plugin.yaml").write_text(
        "name: greeter\nversion: 2.0.0\nkind: standalone\ndescription: greeter does a thing\n"
    )
    hub_repo["index"].write_text(json.dumps(build_index(hub_repo["root"], source="local")), encoding="utf-8")
    plan = plan_update("greeter")
    assert plan.changed == {"__init__.py": "removed", "extra.py": "added", "plugin.yaml": "changed"}
    assert plan.summary() == "greeter: 1 added, 1 removed, 1 changed"
    assert plan.lines() == [
        "  removed  __init__.py",
        "  added    extra.py",
        "  changed  plugin.yaml",
    ]
    apply_update(plan)
    assert installed_plugins()["greeter"]["version"] == "2.0.0"


def test_an_update_that_changes_nothing_is_not_written(hub_repo, plugins_dir):
    install_plugin("greeter")
    plan = plan_update("greeter")
    assert plan.up_to_date and plan.changed == {}
    assert apply_update(plan) == {"name": "greeter", "changed": {}, "updated": False}


def test_an_update_does_not_overwrite_a_locally_edited_plugin_without_force(hub_repo, plugins_dir):
    install_plugin("greeter")
    (plugins_dir / "greeter" / "__init__.py").write_text("# mine\n")
    (hub_repo["greeter"] / "__init__.py").write_text("# theirs\n")
    hub_repo["index"].write_text(json.dumps(build_index(hub_repo["root"], source="local")), encoding="utf-8")
    plan = plan_update("greeter")
    assert plan.edited_locally and plan.summary() == "greeter: 1 changed (edited locally)"
    with pytest.raises(PluginError, match="was edited since it was installed"):
        apply_update(plan)
    assert (plugins_dir / "greeter" / "__init__.py").read_text() == "# mine\n"
    apply_update(plan, force=True)
    assert (plugins_dir / "greeter" / "__init__.py").read_text() == "# theirs\n"


def test_a_plugin_installed_by_hand_is_not_updatable(plugins_dir, clite_home):
    _write_plugin(plugins_dir, "home-made")
    with pytest.raises(PluginError, match="was not installed from a source"):
        plan_update("home-made")


def test_a_source_that_renames_the_plugin_is_refused(hub_repo, plugins_dir):
    install_plugin("greeter")
    (hub_repo["greeter"] / "plugin.yaml").write_text(
        "name: renamed\nversion: 1.0.0\ndescription: greeter does a thing\n"
    )
    with pytest.raises(PluginError, match="the source now calls itself 'renamed'"):
        plan_update("greeter")


# ── command line ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def cli(clite_home, capsys):
    from clite.cli.main import main

    def run(*argv, expect=0, answer=None, monkeypatch=None):
        if answer is not None:
            monkeypatch.setattr("builtins.input", lambda prompt="": answer)
        code = main([str(arg) for arg in argv])
        captured = capsys.readouterr()
        assert code == expect, f"exit {code}\nstdout: {captured.out}\nstderr: {captured.err}"
        return captured.out

    return run


def test_cli_search_and_info(hub_repo, cli):
    output = cli("plugins", "search", "greet")
    assert "greeter" in output and "* = installed" in output
    assert "Nothing matches 'zebra'" in cli("plugins", "search", "zebra", expect=1)
    info = cli("plugins", "info", "greeter")
    assert "no; install it with: clite plugins install greeter" in info
    assert "No plugin named" in cli("plugins", "info", "nope", expect=1)


def test_cli_install_shows_the_dependency_the_user_must_install(hub_repo, cli):
    output = cli("plugins", "install", "greeter")
    assert "Installed greeter 1.0.0" in output
    assert "pip install requests" in output
    assert "clite plugins enable greeter" in output
    info = cli("plugins", "info", "greeter")
    assert "pip install requests" in info and "installed" in info and "local" in info


def test_cli_update_shows_the_diff_and_disables_after_replacing(hub_repo, cli, clite_home, monkeypatch):
    cli("plugins", "install", "greeter")
    config_set("plugins.enabled", ["greeter"])
    (hub_repo["greeter"] / "__init__.py").write_text("# theirs\n")
    hub_repo["index"].write_text(json.dumps(build_index(hub_repo["root"], source="local")), encoding="utf-8")

    output = cli("plugins", "update", "greeter", "--yes")
    assert "greeter: 1 changed" in output
    assert "changed  __init__.py" in output
    assert "disabled until you enable it" in output

    from clite.core.config import load_config

    assert "greeter" in load_config()["plugins"]["disabled"]
    assert "up to date" in cli("plugins", "update")


def test_cli_update_asks_before_replacing(hub_repo, cli, clite_home, monkeypatch):
    cli("plugins", "install", "greeter")
    (hub_repo["greeter"] / "__init__.py").write_text("# theirs\n")
    hub_repo["index"].write_text(json.dumps(build_index(hub_repo["root"], source="local")), encoding="utf-8")
    refused = cli("plugins", "update", "greeter", answer="n", monkeypatch=monkeypatch)
    assert "skipped" in refused
    assert (clite_home / "plugins" / "greeter" / "__init__.py").read_text() != "# theirs\n"
    accepted = cli("plugins", "update", "greeter", answer="y", monkeypatch=monkeypatch)
    assert "Updated greeter" in accepted


def test_cli_update_with_nothing_installed(hub_repo, cli):
    assert "nothing to update" in cli("plugins", "update")


def test_cli_remove_refuses_a_name_that_escapes_the_plugins_directory(clite_home, cli):
    victim = clite_home / "victim"
    victim.mkdir()
    (victim / "plugin.yaml").write_text("name: victim\n")
    assert "No user-installed plugin" in cli("plugins", "remove", "../victim", expect=1)
    assert victim.is_dir() and (victim / "plugin.yaml").is_file()


def test_remove_refuses_a_symlinked_plugin_directory(plugins_dir, clite_home):
    outside = clite_home / "elsewhere" / "linked"
    outside.mkdir(parents=True)
    (outside / "plugin.yaml").write_text("name: linked\n")
    plugins_dir.mkdir(parents=True, exist_ok=True)
    (plugins_dir / "linked").symlink_to(outside, target_is_directory=True)

    assert remove_plugin("linked") is False  # a symlink is refused, not followed
    assert (outside / "plugin.yaml").is_file()
