#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ -x ".venv/bin/pytest" ]; then
    PYTEST_BIN=".venv/bin/pytest"
elif [ -x "venv/bin/pytest" ]; then
    PYTEST_BIN="venv/bin/pytest"
else
    PYTEST_BIN="pytest"
fi

if [ "$#" -eq 0 ]; then
    set -- tests/ -q
fi

MODE="${1:-}"
if [ "$MODE" = "coverage" ]; then
    shift
    echo "AI Engine test suite with coverage — $PYTEST_BIN"
    exec "$PYTEST_BIN" tests/ --cov=app --cov-report=term-missing \
        --cov-report=html:var/coverage_html "$@"
fi

echo "AI Engine test suite — $PYTEST_BIN $*"
exec "$PYTEST_BIN" "$@"
