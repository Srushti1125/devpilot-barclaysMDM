#!/usr/bin/env bash
# ==============================================================================
# DevPilot Backend Automated Test Runner
#
# Usage:
#   ./run_tests.sh                # Run all 78 tests
#   ./run_tests.sh unit           # Run unit tests only
#   ./run_tests.sh repo           # Run repository tests only
#   ./run_tests.sh integration    # Run API integration tests only
#   ./run_tests.sh contract       # Run OpenAPI contract tests only
#   ./run_tests.sh coverage       # Run all tests with code coverage report
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Locate python/pytest in virtualenv or system
if [ -f ".venv/bin/pytest" ]; then
    PYTEST_BIN=".venv/bin/pytest"
elif [ -f "venv/bin/pytest" ]; then
    PYTEST_BIN="venv/bin/pytest"
else
    PYTEST_BIN="pytest"
fi

MODE="${1:-all}"

echo "=========================================================="
echo " DevPilot Backend Test Suite — Mode: $MODE"
echo " Runner: $PYTEST_BIN"
echo "=========================================================="

case "$MODE" in
    unit)
        $PYTEST_BIN tests/unit/ -v
        ;;
    repo|repositories)
        $PYTEST_BIN tests/repositories/ -v
        ;;
    integration)
        $PYTEST_BIN tests/integration/ -v
        ;;
    contract)
        $PYTEST_BIN tests/contract/ -v
        ;;
    coverage)
        $PYTEST_BIN tests/ --cov=app --cov-report=term-missing --cov-report=html:var/coverage_html
        echo ""
        echo "HTML coverage report generated at: var/coverage_html/index.html"
        ;;
    all)
        $PYTEST_BIN tests/ -v
        ;;
    *)
        echo "Unknown mode: $MODE"
        echo "Valid options: all | unit | repo | integration | contract | coverage"
        exit 1
        ;;
esac

echo ""
echo "=========================================================="
echo " Tests completed successfully!"
echo "=========================================================="
