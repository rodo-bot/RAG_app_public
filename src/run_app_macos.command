#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo "Run ./setup_macos.sh first."
  read -r -p "Press Return to close..." _
  exit 1
fi

exec .venv/bin/python -m ragkb.desktop_entry
