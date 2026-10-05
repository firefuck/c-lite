"""Profiles are separate homes; -p is applied before anything reads the home."""

import os

import pytest

from clite.core import profiles
from clite.core.constants import get_default_root, get_home, home_scope, profile_home
from clite.core.errors import ProfileError


def test_default_profile_always_listed():
    assert [p.name for p in profiles.list_profiles()] == ["default"]


def test_create_clone_copies_settings_but_not_secrets():
    root = get_default_root()
    (root / "config.yaml").write_text("display:\n  skin: mono\n")
    (root / ".env").write_text("BOT_TOKEN=secret\n")
    (root / "skills" / "note").mkdir(parents=True)
    (root / "skills" / "note" / "SKILL.md").write_text("---\nname: note\n---\n")
    home = profiles.create_profile("work", clone_from="default")
    assert (home / "config.yaml").read_text() == "display:\n  skin: mono\n"
    assert (home / "skills" / "note" / "SKILL.md").is_file()
    assert not (home / ".env").exists()


def test_active_profile_follows_the_bound_home():
    profiles.create_profile("work")
    assert profiles.get_active_profile_name() == "default"
    with home_scope(profile_home("work")):
        assert profiles.get_active_profile_name() == "work"


@pytest.mark.parametrize("bad", ["Work", "a b", "../x", "", "x" * 40])
def test_invalid_names_are_rejected(bad):
    with pytest.raises(ProfileError):
        profiles.create_profile(bad)


def test_profile_flag_is_consumed_and_points_home_at_the_profile(monkeypatch):
    monkeypatch.delenv("CLITE_HOME")
    profiles.create_profile("work")
    remaining = profiles.apply_profile_override(["-p", "work", "chat", "-q", "hi"])
    assert remaining == ["chat", "-q", "hi"]
    assert os.environ["CLITE_HOME"] == str(profile_home("work"))
    assert get_home() == profile_home("work")


def test_unknown_profile_fails_instead_of_creating_one(monkeypatch):
    monkeypatch.delenv("CLITE_HOME")
    with pytest.raises(ProfileError):
        profiles.apply_profile_override(["--profile=ghost", "status"])
    assert not profile_home("ghost").exists()


def test_sticky_profile_applies_only_without_an_explicit_home(monkeypatch):
    profiles.create_profile("work")
    profiles.set_sticky_profile("work")
    explicit = os.environ["CLITE_HOME"]
    assert profiles.apply_profile_override(["status"]) == ["status"]
    assert os.environ["CLITE_HOME"] == explicit
    monkeypatch.delenv("CLITE_HOME")
    profiles.apply_profile_override(["status"])
    assert os.environ["CLITE_HOME"] == str(profile_home("work"))


def test_deleting_the_sticky_profile_falls_back_to_default():
    profiles.create_profile("work")
    profiles.set_sticky_profile("work")
    profiles.delete_profile("work")
    assert profiles.get_sticky_profile() == "default"
    with pytest.raises(ProfileError):
        profiles.delete_profile("default")
