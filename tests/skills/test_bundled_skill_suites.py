"""The test suites that ship inside bundled skills, run as part of this suite.

A skill keeps its own tests next to its scripts (``<skill>/tests/``), outside ``tests/``, so
pytest would never collect them. Each suite runs here in a child pytest when the libraries
its scripts use are installed, and is skipped with the missing names otherwise: they are
the skill's dependencies, not the project's.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2] / "src" / "clite" / "bundled" / "skills"

# The import names each skill's tests need. A suite missing here fails the coverage test below.
SUITE_REQUIREMENTS = {
    "productivity/docx": ("docx",),
    "productivity/pdf": ("pypdf", "reportlab"),
    "productivity/powerpoint": ("pptx",),
    "productivity/xlsx": ("openpyxl",),
}


def _suites() -> list[str]:
    return sorted(
        path.parent.parent.relative_to(SKILLS).as_posix() for path in SKILLS.glob("**/tests/test_*.py")
    )


def test_every_bundled_skill_suite_is_listed_with_its_requirements():
    assert _suites() == sorted(SUITE_REQUIREMENTS)


@pytest.mark.parametrize("skill", sorted(SUITE_REQUIREMENTS))
def test_the_bundled_skill_suite_passes(skill):
    missing = [name for name in SUITE_REQUIREMENTS[skill] if importlib.util.find_spec(name) is None]
    if missing:
        pytest.skip(f"the {skill} skill's tests need {', '.join(missing)}")
    # No byte caches: they would land inside the skill directory that ships.
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(SKILLS / skill / "tests")],
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
    )
    assert result.returncode == 0, result.stdout[-4000:] + result.stderr[-2000:]
