"""Secrets: .env is the profile's source of truth, and a bound scope never leaks."""

import os
import stat

import pytest

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


def test_secret_names_cover_env_file_registered_and_numbered_variables(monkeypatch):
    get_env_path().write_text("FROM_DOTENV=1\n")
    env.load_env()
    monkeypatch.setitem(env.SECRET_REGISTRY, "EXAMPLE_SERVICE_KEY", env.SecretSpec("EXAMPLE_SERVICE_KEY", "An example"))
    monkeypatch.setenv("EXAMPLE_SERVICE_KEY_3", "third key of a pool")
    names = env.secret_names()
    assert {"FROM_DOTENV", "EXAMPLE_SERVICE_KEY", "EXAMPLE_SERVICE_KEY_3"} <= names
    assert "EXAMPLE_SERVICE_KEY_4" not in names and "PATH" not in names


def test_redaction_masks_scoped_secrets_and_known_process_values(monkeypatch):
    from clite.core.redact import REDACTED, redact

    monkeypatch.setitem(env.SECRET_REGISTRY, "EXAMPLE_KEY", env.SecretSpec("EXAMPLE_KEY", "Example"))
    monkeypatch.setenv("EXAMPLE_KEY", "launch-profile-secret")
    for value in ("first-profile-secret", "second-profile-secret"):
        with env.secret_scope({"EXAMPLE_KEY": value, "LOCAL_ONLY": "local-only-secret",
                               "EXAMPLE_KEY_2": "numbered-scope-secret"}):
            assert redact(f"{value} launch-profile-secret local-only-secret numbered-scope-secret") == " ".join([REDACTED] * 4)
            assert env.get_secret("EXAMPLE_KEY") == value
    assert redact("first-profile-secret second-profile-secret") == "first-profile-secret second-profile-secret"


@pytest.mark.parametrize("scoped,process", [
    ("shared-secret", "shared-secret-extended"),
    ("shared-secret-extended", "shared-secret"),
])
def test_redaction_masks_overlapping_scoped_and_process_secrets_completely(monkeypatch, scoped, process):
    from clite.core.redact import REDACTED, redact

    monkeypatch.setenv("OVERLAPPING_KEY", process)
    with env.secret_scope({"OVERLAPPING_KEY": scoped}):
        assert redact(f"{scoped} {process}") == f"{REDACTED} {REDACTED}"


def test_scoped_secret_names_are_restored_after_a_nested_scope_raises():
    with env.secret_scope({"OUTER_ONLY_KEY": "outer-scope-secret"}):
        assert "OUTER_ONLY_KEY" in env.secret_names()
        with pytest.raises(ValueError), env.secret_scope({"INNER_ONLY_KEY": "inner-scope-secret"}):
            assert "INNER_ONLY_KEY" in env.secret_names()
            assert "OUTER_ONLY_KEY" not in env.secret_names()
            raise ValueError("leave the inner scope")
        assert "OUTER_ONLY_KEY" in env.secret_names()
        assert "INNER_ONLY_KEY" not in env.secret_names()
    assert not {"OUTER_ONLY_KEY", "INNER_ONLY_KEY"} & env.secret_names()
