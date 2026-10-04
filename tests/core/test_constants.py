"""Home resolution: override beats environment beats default, and nothing is frozen."""

from pathlib import Path

from clite.core import constants


def test_home_comes_from_environment(clite_home):
    assert constants.get_home() == clite_home
    assert constants.get_config_path() == clite_home / "config.yaml"


def test_override_wins_and_is_restored(clite_home, tmp_path):
    other = tmp_path / "other-home"
    with constants.home_scope(other):
        assert constants.get_home() == other
        assert constants.get_skills_dir() == other / "skills"
    assert constants.get_home() == clite_home


def test_default_root_ignores_override_and_environment(clite_home, tmp_path):
    with constants.home_scope(tmp_path / "elsewhere"):
        assert constants.get_default_root() == Path.home() / ".clite"


def test_home_key_is_stable_for_equivalent_paths(tmp_path):
    target = tmp_path / "a" / "b"
    assert constants.home_key(target) == constants.home_key(tmp_path / "a" / "." / "b")
    assert constants.home_key(target) != constants.home_key(tmp_path / "a")


def test_display_home_hides_the_user_directory(clite_home):
    assert constants.display_home() == "~/.clite"
    assert constants.display_home(Path("/srv/agent")) == "/srv/agent"


def test_bundled_dir_ships_with_the_package():
    assert constants.bundled_dir().is_dir()
