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

SCRIPT_PATH="${BASH_SOURCE[0]//\\//}"
SCRIPT_DIR="${SCRIPT_PATH%/*}"
[ "$SCRIPT_DIR" = "$SCRIPT_PATH" ] && SCRIPT_DIR="."
PLUGIN_DIR="$(cd "$SCRIPT_DIR/.." && pwd -P)"
PROJECT_DIR="$(pwd -P)"

# Resolve helpers from an absolute PATH entry outside the project before
# executing them. Initializers commonly run from untrusted project roots, so
# relative PATH entries (including the current directory) and project-local
# shims must not be eligible to run.
find_path_executable() {
  local executable="$1"
  local symlink_policy="${2:-allow_symlinks}"
  local entry canonical_entry candidate candidate_name
  local original_ifs="$IFS"
  local candidate_names=("$executable" "${executable}.exe" "${executable}.com" "${executable}.bat" "${executable}.cmd")

  IFS=:
  for entry in $PATH; do
    [ -n "$entry" ] || continue
    case "$entry" in
      /*) ;;
      *) continue ;;
    esac

    canonical_entry="$(cd -P -- "$entry" 2>/dev/null && pwd -P)" || continue
    case "$canonical_entry" in
      "$PROJECT_DIR"|"$PROJECT_DIR"/*) continue ;;
    esac

    for candidate_name in "${candidate_names[@]}"; do
      candidate="$canonical_entry/$candidate_name"
      if [ "$symlink_policy" = "reject_symlinks" ] && [ -L "$candidate" ]; then
        continue
      fi
      if [ -f "$candidate" ] && [ -x "$candidate" ]; then
        printf '%s\n' "$candidate"
        IFS="$original_ifs"
        return 0
      fi
    done
  done
  IFS="$original_ifs"
  return 1
}

resolve_gnu_readlink() {
  local executable candidate

  for executable in readlink greadlink; do
    while IFS= read -r candidate; do
      if "$candidate" -f / >/dev/null 2>&1; then
        printf '%s\n' "$candidate"
        return 0
      fi
    done < <(find_path_executable "$executable" reject_symlinks)
  done
  return 1
}

if ! READLINK_BIN="$(resolve_gnu_readlink)"; then
  READLINK_BIN=""
fi

canonicalize_executable_candidate() {
  local candidate="$1"
  local candidate_dir candidate_base canonical_dir

  if [ -n "$READLINK_BIN" ]; then
    "$READLINK_BIN" -f -- "$candidate" 2>/dev/null
    return $?
  fi

  # BSD/macOS readlink does not support -f. Without a trusted full file
  # canonicalizer, reject symlink executables and safely canonicalize the
  # containing directory only.
  if [ -L "$candidate" ]; then
    return 1
  fi

  candidate_dir="${candidate%/*}"
  candidate_base="${candidate##*/}"
  canonical_dir="$(cd -P -- "$candidate_dir" 2>/dev/null && pwd -P)" || return 1
  printf '%s/%s\n' "$canonical_dir" "$candidate_base"
}

resolve_trusted_executable() {
  local executable="$1"
  local candidate canonical_candidate

  while IFS= read -r candidate; do
    canonical_candidate="$(canonicalize_executable_candidate "$candidate")" || continue
    case "$canonical_candidate" in
      /*) ;;
      *) continue ;;
    esac
    case "$canonical_candidate" in
      "$PROJECT_DIR"|"$PROJECT_DIR"/*) continue ;;
    esac
    if [ -f "$canonical_candidate" ] && [ -x "$canonical_candidate" ]; then
      printf '%s\n' "$canonical_candidate"
      return 0
    fi
  done < <(find_path_executable "$executable")
  return 1
}

for helper in mkdir mktemp rm cmp cp grep; do
  if ! resolve_trusted_executable "$helper" >/dev/null; then
    echo "error: unable to resolve a trusted $helper executable"
    exit 1
  fi
done

MKDIR_BIN="$(resolve_trusted_executable mkdir)"
MKTEMP_BIN="$(resolve_trusted_executable mktemp)"
RM_BIN="$(resolve_trusted_executable rm)"
CMP_BIN="$(resolve_trusted_executable cmp)"
CP_BIN="$(resolve_trusted_executable cp)"
GREP_BIN="$(resolve_trusted_executable grep)"

if [ ! -f "$PLUGIN_DIR/hooks/hooks.json" ]; then
  echo "error: plugin hooks.json not found at $PLUGIN_DIR/hooks/hooks.json"
  echo "       run this script from inside a tailtest-codex checkout."
  exit 1
fi

"$MKDIR_BIN" -p "$PROJECT_DIR/.codex"

if PYTHON_BIN="$(resolve_trusted_executable python3)" && "$PYTHON_BIN" -c "import json" >/dev/null 2>&1; then
  :
elif PYTHON_BIN="$(resolve_trusted_executable python)" && "$PYTHON_BIN" -c "import json" >/dev/null 2>&1; then
  :
else
  echo "error: Python is required to initialize tailtest hooks"
  exit 1
fi

PLUGIN_DIR_NATIVE="$PLUGIN_DIR"
if CYGPATH_BIN="$(resolve_trusted_executable cygpath)"; then
  PLUGIN_DIR_NATIVE="$("$CYGPATH_BIN" -w "$PLUGIN_DIR")"
fi

DESIRED_HOOKS="$("$MKTEMP_BIN" "${TMPDIR:-/tmp}/tailtest-hooks.XXXXXX.json")"
cleanup() {
  "$RM_BIN" -f "$DESIRED_HOOKS"
}
trap cleanup EXIT

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
  if "$CMP_BIN" -s "$DESIRED_HOOKS" "$PROJECT_DIR/.codex/hooks.json"; then
    echo "tailtest: .codex/hooks.json already matches plugin config, nothing to do"
  else
    echo "tailtest: .codex/hooks.json already exists with different content"
    echo "          writing plugin config to .codex/hooks.json.tailtest instead"
    echo "          merge the SessionStart, PostToolUse, and Stop entries manually"
    "$CP_BIN" "$DESIRED_HOOKS" "$PROJECT_DIR/.codex/hooks.json.tailtest"
  fi
else
  "$CP_BIN" "$DESIRED_HOOKS" "$PROJECT_DIR/.codex/hooks.json"
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
  if "$GREP_BIN" -qE '^[[:space:]]*codex_hooks[[:space:]]*=[[:space:]]*true' "$GLOBAL_CONFIG"; then
    echo ""
    echo "note: ~/.codex/config.toml uses the deprecated [features].codex_hooks key."
    echo "      Codex 0.129.0+ accepts it as an alias but emits a deprecation warning"
    echo "      on every session start. Rename it to [features].hooks when convenient."
    echo ""
  elif "$GREP_BIN" -qE '^[[:space:]]*hooks[[:space:]]*=[[:space:]]*true' "$GLOBAL_CONFIG"; then
    : # explicit hooks = true, all good
  else
    : # Codex 0.129.0+ defaults to on; nothing to warn about.
  fi
fi

echo ""
echo "tailtest initialized in $PROJECT_DIR"
echo "start a codex session here; SessionStart fires at boot, PostToolUse fires after each apply_patch, Stop sweeps at turn end."
