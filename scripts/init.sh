#!/bin/bash
# tailtest-codex -- per-project init helper.
#
# Usage (from any project root):
#   bash ~/.codex/plugins/tailtest/scripts/init.sh
#
# This creates .codex/hooks.json in the current directory pointing at the
# tailtest hook scripts, so Codex fires SessionStart and Stop hooks while
# you work in this project. Run once per project.
#
# Prerequisites:
#   1. Plugin cloned to ~/.codex/plugins/tailtest (or accessible PLUGIN_DIR)
#   2. codex_hooks feature flag enabled in ~/.codex/config.toml (the script
#      warns if this is missing).

set -e

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_DIR="$(pwd)"

if [ ! -f "$PLUGIN_DIR/hooks/hooks.json" ]; then
  echo "error: plugin hooks.json not found at $PLUGIN_DIR/hooks/hooks.json"
  echo "       run this script from inside a tailtest-codex checkout."
  exit 1
fi

mkdir -p "$PROJECT_DIR/.codex"

if [ -e "$PROJECT_DIR/.codex/hooks.json" ]; then
  if cmp -s "$PLUGIN_DIR/hooks/hooks.json" "$PROJECT_DIR/.codex/hooks.json"; then
    echo "tailtest: .codex/hooks.json already matches plugin config, nothing to do"
  else
    echo "tailtest: .codex/hooks.json already exists with different content"
    echo "          writing plugin config to .codex/hooks.json.tailtest instead"
    echo "          merge the SessionStart and Stop entries manually"
    cp "$PLUGIN_DIR/hooks/hooks.json" "$PROJECT_DIR/.codex/hooks.json.tailtest"
  fi
else
  cp "$PLUGIN_DIR/hooks/hooks.json" "$PROJECT_DIR/.codex/hooks.json"
  echo "tailtest: wrote .codex/hooks.json -> $PLUGIN_DIR/hooks/"
fi

# Check global codex_hooks feature flag
GLOBAL_CONFIG="$HOME/.codex/config.toml"
if [ -f "$GLOBAL_CONFIG" ] && grep -qE '^[[:space:]]*codex_hooks[[:space:]]*=[[:space:]]*true' "$GLOBAL_CONFIG"; then
  :
else
  echo ""
  echo "note: codex_hooks feature flag is not enabled in $GLOBAL_CONFIG"
  echo "      add this to enable hooks across all projects (one-time setup):"
  echo ""
  echo "      [features]"
  echo "      codex_hooks = true"
  echo ""
fi

echo ""
echo "tailtest initialized in $PROJECT_DIR"
echo "start a codex session here; SessionStart fires immediately, Stop fires at end of each turn."
