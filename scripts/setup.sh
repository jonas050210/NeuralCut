#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON_BIN="${PYTHON:-python3}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || {
  echo "Python 3.10+ is required but was not found." >&2
  exit 1
}
"$PYTHON_BIN" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else "Python 3.10+ is required")'

if [ ! -x .venv/bin/python ]; then
  "$PYTHON_BIN" -m venv .venv
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

echo "NeuralCut setup complete."
echo "Run: ./scripts/run.sh"
echo "Test: ./scripts/test.sh"
