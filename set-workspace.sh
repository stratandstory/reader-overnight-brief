#!/bin/bash
# Saves the workspace ID (starts with wrkspc_) next to your API key in .env.
# Needed only for keys that work across several workspaces. Your key is left as it is.
set -e
cd "$(dirname "$0")"
if [ ! -f .env ]; then
  echo "No API key saved yet. Run ./set-api-key.sh first."
  exit 1
fi
echo "Paste the workspace ID (it starts with wrkspc_), then press Return."
read -r WORKSPACE
WORKSPACE="$(printf '%s' "$WORKSPACE" | tr -d '[:space:]')"
if [[ "$WORKSPACE" != wrkspc_* ]]; then
  echo "A workspace ID starts with wrkspc_. Nothing was changed."
  exit 1
fi
umask 077
grep -v '^ANTHROPIC_WORKSPACE_ID=' .env > .env.tmp || true
printf 'ANTHROPIC_WORKSPACE_ID=%s\n' "$WORKSPACE" >> .env.tmp
mv .env.tmp .env
chmod 600 .env
echo "Saved. Checking access (free)..."
./brief doctor
