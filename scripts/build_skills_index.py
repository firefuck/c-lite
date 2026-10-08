#!/usr/bin/env python3
"""Build a skill index from a directory tree of skills.

    python scripts/build_skills_index.py                         # the bundled skills
    python scripts/build_skills_index.py --root ./skills-hub \
        --identifier-prefix acme/skills --out skills-index.json

The index is one JSON file: a name, description, category, source, identifier and content hash
for every ``SKILL.md`` under ``--root``. ``clite skills search`` reads it, and ``clite skills
install <name>`` fetches the entry's identifier and checks that what arrived matches the hash.

The bundled index (``src/clite/bundled/skills-index.json``) is generated with no arguments and
is committed; a test keeps it in step with the bundled skills.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Where the bundled skills live in this project's own repository. The bundled index lists them
# with this prefix, so `clite skills install <name>` fetches the same files over GitHub and the
# hash in the index still matches.
BUNDLED_PREFIX = "dragovics/clite/src/clite/bundled/skills"
sys.path.insert(0, str(ROOT / "src"))

# Build with a throwaway home: what the index holds must not depend on the machine it ran on.
os.environ.setdefault("CLITE_HOME", tempfile.mkdtemp(prefix="clite-skills-index-"))
for _name in [key for key in os.environ if key.startswith("CLITE_") and key != "CLITE_HOME"]:
    del os.environ[_name]

from clite.skills.hub import build_index  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        default=str(ROOT / "src" / "clite" / "bundled" / "skills"),
        help="directory holding the skills (default: the bundled ones)",
    )
    parser.add_argument(
        "--source",
        default="github",
        help="which source installs these skills: github, local, or a registered source (default: github)",
    )
    parser.add_argument(
        "--identifier-prefix",
        default=BUNDLED_PREFIX,
        help=f"prepended to each skill's path, e.g. owner/repo when --source github "
        f"(default: {BUNDLED_PREFIX})",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "src" / "clite" / "bundled" / "skills-index.json"),
        help="where to write the index",
    )
    args = parser.parse_args(argv)

    document = build_index(args.root, source=args.source, identifier_prefix=args.identifier_prefix)
    text = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"{len(document['skills'])} skill(s) -> {out}")
    for entry in document["skills"]:
        print(f"  {entry['name']:<30} {entry['category'] or 'general':<22} {entry['hash'][:19]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
