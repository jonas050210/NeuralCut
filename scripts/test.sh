#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
  echo "Virtual environment not found. Run ./scripts/setup.sh first." >&2
  exit 1
fi

.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check neuralcut
node --check neuralcut/frontend/assets/app.js
