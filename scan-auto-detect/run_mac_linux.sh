#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo " [ERROR] python3 not found"
  exit 1
fi

echo
echo " ============================================"
echo "  Deye Auto Detect (macOS / Linux)"
echo " ============================================"
echo

"$PYTHON_BIN" "$SCRIPT_DIR/deye_auto_detect.py" "$@"
