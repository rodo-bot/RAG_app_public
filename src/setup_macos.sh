#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.11 or newer is required. Install it from https://www.python.org/downloads/macos/"
  exit 1
fi

if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi

.venv/bin/python -m pip install --disable-pip-version-check --upgrade pip
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
.venv/bin/python - <<'PY'
from fastembed import TextEmbedding
from pathlib import Path

model = TextEmbedding(
    model_name="BAAI/bge-small-en-v1.5",
    cache_dir=Path("models"),
)
print("Local embedding dimensions:", len(next(model.embed(["ready"]))))
PY

if ! command -v tesseract >/dev/null 2>&1; then
  echo "Optional OCR is not installed. If Homebrew is available, run: brew install tesseract"
fi

echo "RAG Knowledge Base is ready. Double-click run_app_macos.command to start it."
