#!/usr/bin/env bash
set -euo pipefail

# Dabba Test Runner
# Runs the full test suite with optional coverage

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Default values
COVERAGE=${COVERAGE:-false}
VERBOSE=${VERBOSE:-false}
TEST_PATH=${TEST_PATH:-"tests/"}
PARALLEL=${PARALLEL:-false}
MARKERS=${MARKERS:-""}

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Running Dabba test suite...${NC}"
echo "Project directory: $PROJECT_DIR"
echo "Test path: $TEST_PATH"
echo ""

# Build pytest arguments
PYTEST_ARGS=()

if [ "$VERBOSE" = true ]; then
    PYTEST_ARGS+=("-v")
fi

if [ "$COVERAGE" = true ]; then
    PYTEST_ARGS+=("--cov=dabba")
    PYTEST_ARGS+=("--cov-report=term-missing")
    PYTEST_ARGS+=("--cov-report=html")
fi

if [ "$PARALLEL" = true ]; then
    PYTEST_ARGS+=("-n")
    PYTEST_ARGS+=("auto")
fi

if [ -n "$MARKERS" ]; then
    PYTEST_ARGS+=("-m")
    PYTEST_ARGS+=("$MARKERS")
fi

PYTEST_ARGS+=("$TEST_PATH")

# Run tests
set -x
python -m pytest "${PYTEST_ARGS[@]}"
set +x

EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
else
    echo -e "${RED}Some tests failed (exit code: $EXIT_CODE)${NC}"
fi

exit $EXIT_CODE
