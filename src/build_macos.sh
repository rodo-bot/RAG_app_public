#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Run ./setup_macos.sh first."
  exit 1
fi

.venv/bin/python -m pip install --disable-pip-version-check pyinstaller
rm -rf build/macos-desktop build/macos-mcp \
  "dist/RAG Knowledge Base" "dist/RAG Knowledge Base.app" \
  "dist/RAG Knowledge Base MCP"

.venv/bin/python -m PyInstaller \
  --noconfirm \
  --windowed \
  --collect-binaries sqlite_vec \
  --name "RAG Knowledge Base" \
  --workpath build/macos-desktop \
  --distpath dist \
  "RAG Knowledge Base Desktop.pyw"

.venv/bin/python -m PyInstaller \
  --noconfirm \
  --onefile \
  --console \
  --collect-binaries sqlite_vec \
  --name "RAG Knowledge Base MCP" \
  --workpath build/macos-mcp \
  --distpath dist \
  "RAG Knowledge Base MCP.py"

codesign --force --deep --sign - "dist/RAG Knowledge Base.app"
echo "Built dist/RAG Knowledge Base.app and dist/RAG Knowledge Base MCP."
