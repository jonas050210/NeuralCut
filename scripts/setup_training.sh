#!/usr/bin/env bash
# Create the SEPARATE training environment (Linux/macOS equivalent).
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -x .venv-training/bin/python ]; then
  python3 -m venv .venv-training
fi
.venv-training/bin/python -m pip install --upgrade pip
.venv-training/bin/python -m pip install torch --index-url https://download.pytorch.org/whl/cu124
.venv-training/bin/python -m pip install -r requirements-training.txt
echo "Training env ready. Next:"
echo "  .venv-training/bin/python -m neuralcut.training.train_qlora --preflight"
