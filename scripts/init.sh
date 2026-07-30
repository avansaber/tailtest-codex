#!/bin/bash
# tailtest-codex -- per-project init helper.
#
# Usage (from any project root):
#   bash ~/.codex/plugins/tailtest/scripts/init.sh
#
# This creates .codex/hooks.json in the current directory with absolute
# commands for the tailtest hook scripts, so Codex fires SessionStart,
# PostToolUse, and Stop hooks while you work in this project. Run once per
# project when using a direct clone rather than the Codex marketplace.
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

if command -v python3 >/dev/null 2>&1 && python3 -c "import json" >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1 && python -c "import json" >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "error: Python is required to initialize tailtest hooks"
  exit 1
fi

PLUGIN_DIR_NATIVE="$PLUGIN_DIR"
if command -v cygpath >/dev/null 2>&1; then
  PLUGIN_DIR_NATIVE="$(cygpath -w "$PLUGIN_DIR")"
fi

DESIRED_HOOKS="$(mktemp "${TMPDIR:-/tmp}/tailtest-hooks.XXXXXX.json")"
trap 'rm -f "$DESIRED_HOOKS"' EXIT

"$PYTHON_BIN" - "$PLUGIN_DIR_NATIVE" "$PLUGIN_DIR/hooks/hooks.json" "$DESIRED_HOOKS" <<'PY'
import json
import sys

plugin_root, source_path, output_path = sys.argv[1:]
plugin_root = plugin_root.replace("\\", "/").rstrip("/")
if '"' in plugin_root:
    raise SystemExit("error: plugin path contains an unsupported double quote")

with open(source_path, encoding="utf-8") as source:
    config = json.load(source)

for groups in config["hooks"].values():
    for group in groups:
        for handler in group["hooks"]:
            script_name = handler["command"].rsplit("/", 1)[-1].rstrip('"')
            handler["command"] = (
                'TAILTEST_PROJECT_CWD="$PWD"; export TAILTEST_PROJECT_CWD; '
                f'cd -- "{plugin_root}" && '
                f'python3 "{plugin_root}/hooks/{script_name}"'
            )
            handler["commandWindows"] = (
                'set "TAILTEST_PROJECT_CWD=%CD%" && '
                f'cd /d "{plugin_root}" && '
                f'python "{plugin_root}/hooks/{script_name}"'
            )

with open(output_path, "w", encoding="utf-8", newline="\n") as output:
    json.dump(config, output, indent=2)
    output.write("\n")
PY

if [ -e "$PROJECT_DIR/.codex/hooks.json" ]; then
  if cmp -s "$DESIRED_HOOKS" "$PROJECT_DIR/.codex/hooks.json"; then
    echo "tailtest: .codex/hooks.json already matches plugin config, nothing to do"
  else
    echo "tailtest: .codex/hooks.json already exists with different content"
    echo "          writing plugin config to .codex/hooks.json.tailtest instead"
    echo "          merge the SessionStart, PostToolUse, and Stop entries manually"
    cp "$DESIRED_HOOKS" "$PROJECT_DIR/.codex/hooks.json.tailtest"
  fi
else
  cp "$DESIRED_HOOKS" "$PROJECT_DIR/.codex/hooks.json"
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
