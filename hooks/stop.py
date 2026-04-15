#!/usr/bin/env python3
"""tailtest Stop hook -- mtime-based file detection and test queueing.

Fires at the end of every Codex agent turn.  Sweeps the project for files
modified during the turn (mtime > session.turn_start_mtime), applies the
intelligence filter, and queues changed source files for test generation.

If files are queued: returns decision=block with a test instruction.
If no files changed: returns decision=continue.

The stop_hook_active guard (set by Codex when the hook itself triggered the
current turn) prevents infinite test loops.

Target: < 500ms on a project with 5,000 files.  No LLM calls.
"""

from __future__ import annotations

import json
import os
import sys
import time

# Ensure the plugin root (parent of hooks/) is on sys.path so that
# `from hooks.lib import ...` works when the hook is run from the user's
# project directory (which is what Codex does).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hooks.lib.filter import (
    RUNNER_REQUIRED_LANGUAGES,
    detect_language,
    is_filtered,
    load_ignore_patterns,
)
from hooks.lib.session import load_session, save_session


def sweep_changed_files(
    project_root: str,
    turn_start_mtime: float,
    ignore_patterns: list[str],
) -> list[dict]:
    """Walk the project and return files modified after turn_start_mtime.

    Returns a list of dicts: [{path: rel_path, language: lang}, ...]
    Only files that pass is_filtered() and have a known language are returned.
    """
    changed: list[dict] = []

    # Directories to prune during the walk (performance bound)
    _skip_dirs = {
        "node_modules", ".venv", "venv", ".env", "env",
        "dist", "build", "generated", ".git", "vendor",
        "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
        "target", ".cargo", "coverage", ".nyc_output",
        ".next", ".nuxt", ".svelte-kit", ".tailtest",
        "migrations", "k8s", "deploy", "infra",
    }

    for root, dirnames, filenames in os.walk(project_root):
        # Prune in-place to avoid descending into noise dirs
        dirnames[:] = [
            d for d in dirnames
            if d not in _skip_dirs and not d.startswith(".")
        ]

        for filename in filenames:
            abs_path = os.path.join(root, filename)

            # Skip symlinks
            if os.path.islink(abs_path):
                continue

            try:
                mtime = os.path.getmtime(abs_path)
            except OSError:
                continue

            # Must be strictly greater (file at exactly turn_start_mtime is pre-existing)
            if mtime <= turn_start_mtime:
                continue

            language = detect_language(abs_path)
            if not language:
                continue

            if is_filtered(abs_path, project_root, ignore_patterns):
                continue

            rel_path = os.path.relpath(abs_path, project_root).replace("\\", "/")
            changed.append({"path": rel_path, "language": language})

    return changed


def main() -> None:
    # Read stdin
    try:
        raw = sys.stdin.read()
        event: dict = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        event = {}

    project_root: str = event.get("cwd", os.getcwd())

    # Loop guard: if Codex set stop_hook_active, this turn was triggered by
    # a previous hook block.  Let it continue so tests can run.
    if event.get("stop_hook_active", False):
        print(json.dumps({"decision": "continue"}))
        return

    # Load session -- graceful no-op if missing
    session = load_session(project_root)
    if not session.get("runners") and not session.get("session_id"):
        # No active tailtest session
        print(json.dumps({"decision": "continue"}))
        return

    # Paused session: update mtime timestamp and continue
    if session.get("paused", False):
        session["turn_start_mtime"] = time.time()
        try:
            save_session(project_root, session)
        except OSError:
            pass
        print(json.dumps({"decision": "continue"}))
        return

    turn_start_mtime: float = session.get("turn_start_mtime", 0.0)
    ignore_patterns = load_ignore_patterns(project_root)
    runners: dict = session.get("runners", {})

    # Sweep for changed files
    changed = sweep_changed_files(project_root, turn_start_mtime, ignore_patterns)

    # Filter out languages that require an explicit runner but none is configured
    qualified: list[dict] = []
    for entry in changed:
        lang = entry["language"]
        if lang in RUNNER_REQUIRED_LANGUAGES and lang not in runners:
            continue
        qualified.append(entry)

    # Update turn_start_mtime now (before writing session) so next turn baseline is correct
    session["turn_start_mtime"] = time.time()

    if not qualified:
        try:
            save_session(project_root, session)
        except OSError:
            pass
        print(json.dumps({"decision": "continue"}))
        return

    # Merge into pending_files (deduplicate by path)
    pending_files: list[dict] = session.get("pending_files", [])
    existing_paths = {p["path"] for p in pending_files}
    newly_queued: list[str] = []

    for entry in qualified:
        if entry["path"] not in existing_paths:
            pending_files.append({
                "path": entry["path"],
                "language": entry["language"],
                "status": "new-file",
            })
            existing_paths.add(entry["path"])
            newly_queued.append(entry["path"])

    session["pending_files"] = pending_files

    try:
        save_session(project_root, session)
    except OSError:
        pass

    if not newly_queued:
        # All changed files were already pending -- nothing new to block for
        print(json.dumps({"decision": "continue"}))
        return

    n = len(newly_queued)
    paths_str = ", ".join(newly_queued[:5])
    if len(newly_queued) > 5:
        paths_str += f" (+{len(newly_queued) - 5} more)"

    reason = (
        f"tailtest: queued {n} file(s) ({paths_str}). "
        f"Read .tailtest/session.json and follow AGENTS.md Step 1."
    )
    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    main()
