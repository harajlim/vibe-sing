#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$DIR/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3 || true)"
fi
if [ -z "$PY" ] || [ ! -x "$PY" ]; then
  echo "vibe-sing: no python interpreter found. Create $DIR/.venv (see README)." >&2
  exit 1
fi
exec "$PY" "$DIR/vibe_sing.py" "$@"
