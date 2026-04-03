#!/usr/bin/env bash
set -euo pipefail

SKIP_PRE_COMMIT=0
TEST_PATTERN="test_*.py"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-pre-commit)
      SKIP_PRE_COMMIT=1
      shift
      ;;
    --pattern)
      TEST_PATTERN="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

if [[ "$SKIP_PRE_COMMIT" -eq 0 ]]; then
  python -m pre_commit run --all-files
fi

python run.py validate --pattern "$TEST_PATTERN"