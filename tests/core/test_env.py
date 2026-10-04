"""Secrets: .env is the profile's source of truth, and a bound scope never leaks."""

import os
import stat

from clite.core import env
from clite.core.constants import get_env_path


def test_env_file_overrides_a_stale_shell_export(monkeypatch):
    monkeypatch.setenv("EXAMPLE_KEY", "stale-from-shell")
    get_env_path().write_text("EXAMPLE_KEY=saved-by-user\n")
    assert env.load_env() == ["EXAMPLE_KEY"]
    assert env.get_secret("EXAMPLE_KEY") == "saved-by-user"
    assert "EXAMPLE_KEY" in env.loaded_secret_names()


def test_save_replaces_in_place_and_restricts_permissions():
    get_env_path().write_text("# comment\nA=1\nB=2\n")
    env.save_secret("A", "new value with spaces")
    env.save_secret("C", "3")
    assert env.read_env_file() == {"A": "new value with spaces", "B": "2", "C": "3"}
    assert get_env_path().read_text().startswith("# comment\n")
    assert stat.S_IMODE(get_env_path().stat().st_mode) == 0o600


def test_remove_reports_whether_anything_changed():
    env.save_secret("A", "1")
    assert env.remove_secret("A") is True
    assert env.remove_secret("A") is False
    assert "A" not in os.environ


def test_bound_scope_does_not_fall_through_to_the_process_environment(monkeypatch):
    monkeypatch.setenv("OTHER_PROFILE_KEY", "belongs-to-launch-profile")
    with env.secret_scope({"MINE": "x"}):
        assert env.get_secret("MINE") == "x"
        assert env.get_secret("OTHER_PROFILE_KEY") is None
        assert env.get_secret("OTHER_PROFILE_KEY", "fallback") == "fallback"
    assert env.get_secret("OTHER_PROFILE_KEY") == "belongs-to-launch-profile"


def test_mask_never_shows_a_short_secret():
    assert env.mask_secret("abcd") == "****"
    assert env.mask_secret("sk-1234567890abcdef") == "sk-1…cdef"
    assert env.mask_secret(None) == "(not set)"
