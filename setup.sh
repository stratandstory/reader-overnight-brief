#!/bin/bash
# One-time setup: creates a private Python environment in .venv and installs three packages.
set -e
cd "$(dirname "$0")"
PY=""
for c in python3.14 python3.13 python3.12 python3.11 python3; do
  # macOS's own /usr/bin/python3 is a stand-in that offers to install Apple's developer tools; skip it when
  # they are not installed (their Python is too old for Reader anyway).
  if [ "$c" = python3 ] && [ "$(uname)" = Darwin ] && [ "$(command -v python3)" = /usr/bin/python3 ] \
     && ! xcode-select -p >/dev/null 2>&1; then
    continue
  fi
  if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
    PY="$c"; break
  fi
done
if [ -z "$PY" ]; then
  echo "Python 3.11 or newer is required. Install it from https://www.python.org/downloads/ (the macOS installer),"
  echo "then run ./setup.sh again."
  exit 1
fi
echo "Using $($PY --version)"
[ -d .venv ] || "$PY" -m venv .venv
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
echo "Setup complete. Next step: ./set-api-key.sh"
[ -f config/local.toml ] || echo "Then choose which sources Reader may read: ./brief choose-sources"
