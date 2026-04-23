#!/usr/bin/env bash

set -euo pipefail

# Always run from the repository root, regardless of caller cwd.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Prefer python3, but fall back to python for environments that only ship one name.
if command -v python3 >/dev/null 2>&1; then
	PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
	PYTHON_BIN="python"
else
	echo "ERROR: Could not find python3 or python in PATH." >&2
	exit 1
fi

echo "Building site for production..."
echo "Using interpreter: $PYTHON_BIN"
"$PYTHON_BIN" src/main.py
echo "Production build complete!"
