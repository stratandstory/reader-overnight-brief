#!/bin/bash
# Saves your Anthropic API key to .env in this folder, readable only by your Mac user.
# The key is never displayed, logged, or sent anywhere except Anthropic's API.
#   ./set-api-key.sh              paste the key when asked
#   ./set-api-key.sh --clipboard  take the key from the clipboard (copy it first), then clear the clipboard.
#                                 For setting up through Claude Code: the key never appears in the chat.
set -e
cd "$(dirname "$0")"
if [ "$1" = "--clipboard" ]; then
  KEY="$(pbpaste 2>/dev/null | tr -d '[:space:]')"
  WORKSPACE=""
  if [[ "$KEY" != sk-ant-* ]]; then
    echo "The clipboard does not hold an Anthropic API key (they start with sk-ant-). Nothing was saved."
    echo "Copy the key in the Claude Console, then run this again."
    exit 1
  fi
else
  echo "Paste your Anthropic API key, then press Return."
  echo "(Nothing appears while you paste. That's normal.)"
  read -r -s KEY
  echo
  KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"
  if [[ "$KEY" != sk-ant-* ]]; then
    echo "That doesn't look like an Anthropic API key (they start with sk-ant-). Nothing was saved."
    exit 1
  fi
  echo
  echo "If your key works across several workspaces, paste the workspace ID (it starts with wrkspc_)."
  echo "Otherwise just press Return."
  read -r WORKSPACE
  WORKSPACE="$(printf '%s' "$WORKSPACE" | tr -d '[:space:]')"
  if [ -n "$WORKSPACE" ] && [[ "$WORKSPACE" != wrkspc_* ]]; then
    echo "A workspace ID starts with wrkspc_. Nothing was saved; run ./set-api-key.sh again."
    exit 1
  fi
fi
umask 077
printf 'ANTHROPIC_API_KEY=%s\n' "$KEY" > .env
if [ -n "$WORKSPACE" ]; then
  printf 'ANTHROPIC_WORKSPACE_ID=%s\n' "$WORKSPACE" >> .env
fi
chmod 600 .env
echo "Saved to .env (readable only by your Mac user)."
if [ "$1" = "--clipboard" ]; then
  printf '' | pbcopy
  echo "The clipboard has been cleared."
fi
if [ -f reader/cli.py ] && [ -x .venv/bin/python ]; then
  echo "Checking the key and model access (free)..."
  ./brief doctor
fi
