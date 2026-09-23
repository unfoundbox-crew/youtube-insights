#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null; then
  echo "python3 is required" >&2; exit 1
fi
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
if [ "${1:-}" = "--semantic" ]; then
  python -m pip install -r requirements-semantic.txt
else
  python -m pip install -r requirements.txt
fi


echo
echo "Setup complete. Try:"
echo "  ./galaxy demo"
echo "  ./galaxy dev"
echo "Then build real data with: ./galaxy build /path/to/takeout.zip"
