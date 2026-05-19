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
#   2. Codex CLI 0.129.0 or newer. In that range hooks are stable and on
#      by default. On older versions add `[features] hooks = true` to
#      ~/.codex/config.toml. The script warns if it detects an older flag.

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

# Hooks feature flag check.
#
# Codex 0.129.0+: hooks are stable and on by default; no config entry needed.
# Older Codex: hooks require [features] hooks = true (or the legacy
#   codex_hooks = true alias, which is still accepted but deprecated).
#
# This block only warns when neither key is set, which usually means the user
# is on an older Codex that needs the flag turned on explicitly.
GLOBAL_CONFIG="$HOME/.codex/config.toml"
if [ -f "$GLOBAL_CONFIG" ]; then
  if grep -qE '^[[:space:]]*codex_hooks[[:space:]]*=[[:space:]]*true' "$GLOBAL_CONFIG"; then
    echo ""
    echo "note: ~/.codex/config.toml uses the deprecated [features].codex_hooks key."
    echo "      Codex 0.129.0+ accepts it as an alias but emits a deprecation warning"
    echo "      on every session start. Rename it to [features].hooks when convenient."
    echo ""
  elif grep -qE '^[[:space:]]*hooks[[:space:]]*=[[:space:]]*true' "$GLOBAL_CONFIG"; then
    : # explicit hooks = true, all good
  else
    : # Codex 0.129.0+ defaults to on; nothing to warn about.
  fi
fi

echo ""
echo "tailtest initialized in $PROJECT_DIR"
echo "start a codex session here; SessionStart fires at boot, PostToolUse fires after each apply_patch, Stop sweeps at turn end."
