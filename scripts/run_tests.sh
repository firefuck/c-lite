#!/usr/bin/env bash
# Run every check the project has: lint, type checks, Python tests, TypeScript tests.
#
#   scripts/run_tests.sh            everything
#   scripts/run_tests.sh lint       ruff and mypy
#   scripts/run_tests.sh python     only the Python suite (extra arguments go to pytest)
#   scripts/run_tests.sh node       only the TypeScript packages
#
# The Python suite needs the package's dependencies and pytest (`pip install -e '.[dev]'`).
# The TypeScript tests run on Node 22+ directly (no build step) and start the real Python
# backend, so they need the same Python environment. Type checks run when `typescript` is
# installed (`npm install` at the repository root); otherwise they are skipped with a note.
set -euo pipefail

cd "$(dirname "$0")/.."
what="${1:-all}"
[ $# -gt 0 ] && shift
python="${PYTHON:-python3}"
export PYTHONPATH="$PWD/src${PYTHONPATH:+:$PYTHONPATH}"
failed=0

run_lint() {
  if command -v ruff >/dev/null; then
    echo "== ruff"
    ruff check src tests scripts || failed=1
  else
    echo "== ruff is not installed: lint skipped (pip install -e '.[dev]')"
  fi
  if command -v mypy >/dev/null; then
    echo "== mypy"
    mypy || failed=1
  else
    echo "== mypy is not installed: type check skipped (pip install -e '.[dev]')"
  fi
}

run_python() {
  echo "== Python tests"
  "$python" -m pytest tests -q "$@" || failed=1
}

# Resolve a module the way Node would from the current directory; print nothing if absent.
node_resolve() {
  node -e "try { process.stdout.write(require.resolve('$1')) } catch {}" 2>/dev/null
}

run_node() {
  if ! command -v node >/dev/null; then
    echo "== Node.js not found: skipping the TypeScript tests"
    return 0
  fi
  for package in apps/shared ui-tui apps/desktop; do
    echo "== $package: tests"
    (cd "$package" && CLITE_PYTHON="$python" node --test test/*.test.ts) || failed=1
    (
      cd "$package"
      tsc="$(node_resolve typescript/bin/tsc)"
      if [ -z "$tsc" ]; then
        echo "== $package: type check skipped (typescript is not installed; run npm install)"
      elif [ "$package" = "apps/desktop" ] && [ -z "$(node_resolve electron)" ]; then
        echo "== $package: type check skipped (electron is not installed; run npm install)"
      else
        echo "== $package: type check"
        node "$tsc" --noEmit -p .
      fi
    ) || failed=1
  done
}

case "$what" in
  lint) run_lint ;;
  python) run_python "$@" ;;
  node) run_node ;;
  all) run_lint; run_python "$@"; run_node ;;
  *) echo "usage: scripts/run_tests.sh [lint|python|node|all] [pytest arguments]" >&2; exit 2 ;;
esac

if [ "$failed" -ne 0 ]; then
  echo "== FAILED"
  exit 1
fi
echo "== all checks passed"
