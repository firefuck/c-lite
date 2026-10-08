#!/usr/bin/env python3
"""Build a plugin catalog from a directory tree of plugins.

    python scripts/build_plugins_index.py                        # the bundled plugins
    python scripts/build_plugins_index.py --root ./plugin-catalog \\
        --identifier-prefix acme/plugins --out plugins-index.json

The catalog is one JSON file: name, description, version, kind, source, identifier and content
hash for every ``plugin.yaml`` under ``--root``. ``clite plugins search`` reads it, and
``clite plugins install <name>`` fetches the entry's identifier and checks that what arrived
matches the hash.

The bundled catalog (``src/clite/bundled/plugins-index.json``) is generated with no arguments
and is committed; a test keeps it in step with the bundled plugins.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Where the bundled plugins live in this project's own repository. The bundled catalog lists
# them with this prefix, so `clite plugins install <name>` fetches the same files over GitHub
# and the hash in the catalog still matches.
BUNDLED_PREFIX = "dragovics/clite/src/clite/bundled/plugins"
sys.path.insert(0, str(ROOT / "src"))

# Build with a throwaway home: what the catalog holds must not depend on the machine it ran on.
os.environ.setdefault("CLITE_HOME", tempfile.mkdtemp(prefix="clite-plugins-index-"))
for _name in [key for key in os.environ if key.startswith("CLITE_") and key != "CLITE_HOME"]:
    del os.environ[_name]

from clite.plugins.hub import build_index  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--root",
        default=str(ROOT / "src" / "clite" / "bundled" / "plugins"),
        help="directory holding the plugins (default: the bundled ones)",
    )
    parser.add_argument(
        "--source",
        default="github",
        help="which source installs these plugins: github, local, or git (default: github)",
    )
    parser.add_argument(
        "--identifier-prefix",
        default=BUNDLED_PREFIX,
        help=f"prepended to each plugin's path, e.g. owner/repo when --source github "
        f"(default: {BUNDLED_PREFIX})",
    )
    parser.add_argument(
        "--out",
        default=str(ROOT / "src" / "clite" / "bundled" / "plugins-index.json"),
        help="where to write the catalog",
    )
    args = parser.parse_args(argv)

    document = build_index(args.root, source=args.source, identifier_prefix=args.identifier_prefix)
    text = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"{len(document['plugins'])} plugin(s) -> {out}")
    for entry in document["plugins"]:
        print(f"  {entry['name']:<28} {entry['kind']:<16} {entry['hash'][:19]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
