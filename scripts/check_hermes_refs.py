#!/usr/bin/env python3
"""Check that every Hermes file the documents cite exists in a Hermes checkout.

The teardown notes (``docs/hermes/``) and the roadmap point at files in the Hermes repository
so that whoever implements a task reads the real code instead of guessing. A pointer to a
file that is not there is worse than no pointer, so run this after editing those documents:

    git clone https://github.com/NousResearch/hermes-agent ../hermes-ref
    git -C ../hermes-ref checkout 1298c8e74baa73e1a2b90124228d017261ac6bc4
    python scripts/check_hermes_refs.py --hermes ../hermes-ref

Exit status: 0 when every reference resolves, 1 when some do not, 2 when ``--hermes`` is not
a Hermes checkout. It is not part of the test suite because the suite must not need a second
repository; ``tests/test_docs.py`` checks the references into *this* repository.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import doc_refs

REPO_ROOT = Path(__file__).resolve().parents[1]
PINNED_COMMIT = "1298c8e74baa73e1a2b90124228d017261ac6bc4"
# Files that identify a Hermes checkout.
MARKERS = ("run_agent.py", "hermes_cli", "tui_gateway")


def looks_like_a_path(path: str, top_level: set[str]) -> bool:
    if path.startswith("."):
        return False  # `.env`, `.ts/.tsx`: a home file or an extension, not a repository path
    if "/" not in path:
        # A bare name is checked only when it is clearly source code. `config.yaml` and
        # `MEMORY.md` are files in the user's home, and `api.example.sh` is a host name.
        return path.endswith(doc_refs.CODE_SUFFIXES) and not (path.endswith(".sh") and path.count(".") > 1)
    if path.endswith("/") or path.endswith(doc_refs.FILE_SUFFIXES):
        return True
    return path.split("/", 1)[0] in top_level  # e.g. `plugins/model-providers`


def resolves(path: str, files: set[str]) -> bool:
    path = path.rstrip("/")
    return path in files or any(name.endswith("/" + path) for name in files)


def checkout_commit(hermes: Path) -> str:
    try:
        result = subprocess.run(["git", "-C", str(hermes), "rev-parse", "HEAD"], capture_output=True, text=True,
                                timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--hermes", required=True, type=Path, help="path to a Hermes checkout")
    parser.add_argument("--quiet", action="store_true", help="print only the problems")
    args = parser.parse_args(argv)

    hermes = args.hermes.expanduser()
    if not all((hermes / marker).exists() for marker in MARKERS):
        print(f"{hermes} is not a Hermes checkout (expected {', '.join(MARKERS)} in it)", file=sys.stderr)
        return 2
    commit = checkout_commit(hermes)
    if commit and commit != PINNED_COMMIT:
        print(f"note: the checkout is at {commit[:12]}, the documents describe {PINNED_COMMIT[:12]}; "
              "files may have moved", file=sys.stderr)

    files = doc_refs.repository_files(hermes)
    top_level = {name.split("/", 1)[0] for name in files}
    checked, missing = 0, []
    for document in doc_refs.documents(REPO_ROOT):
        for token, line in doc_refs.hermes_tokens(document, REPO_ROOT):
            path = doc_refs.normalize(token)
            if path is None or not looks_like_a_path(path, top_level):
                continue
            checked += 1
            if not resolves(path, files):
                missing.append(f"{document.relative_to(REPO_ROOT)}:{line}: `{token}`")
    for entry in missing:
        print(entry)
    if not args.quiet or missing:
        print(f"{checked} Hermes references checked, {len(missing)} not found", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
