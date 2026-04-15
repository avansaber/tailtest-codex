#!/usr/bin/env python3
"""tailtest SessionStart hook -- project orientation and AGENTS.md injection.

Fires on session startup, resume, and compact (post-compaction).

startup / resume:
  - Reads and injects AGENTS.md (plugin intelligence layer)
  - Scans project manifests to detect runners and test locations
  - Creates a fresh .tailtest/session.json (includes turn_start_mtime)
  - Emits project summary via hookSpecificOutput.additionalContext

compact:
  - Re-injects AGENTS.md so the model has instructions after compaction
  - Re-emits session state summary from .tailtest/session.json

Target: < 2 seconds for startup, < 1 second for compact.
"""

from __future__ import annotations

import json
import os
import sys

# Ensure the plugin root (parent of hooks/) is on sys.path so that
# `from hooks.lib import ...` works when the hook is run from the user's
# project directory (which is what Codex does).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hooks.lib.context import (
    build_compact_context,
    build_startup_context,
    read_agents_md,
)
from hooks.lib.ramp_up import _write_orphaned_report, is_first_session, ramp_up_scan
from hooks.lib.runners import create_session, read_depth, scan_runners


def main() -> None:
    try:
        raw = sys.stdin.read()
        event: dict = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        event = {}

    # Codex sends hook_event_name; source field mirrors Claude Code convention
    source: str = event.get("source", event.get("event_type", "startup"))
    project_root: str = event.get("cwd", os.getcwd())

    # Resolve plugin root: CLAUDE_PLUGIN_ROOT env var (Claude Code compat),
    # CODEX_PLUGIN_ROOT env var, or parent directory of this file.
    plugin_root = (
        os.environ.get("CODEX_PLUGIN_ROOT") or
        os.environ.get("CLAUDE_PLUGIN_ROOT") or
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    agents_md = read_agents_md(plugin_root)

    if source == "compact":
        session_path = os.path.join(project_root, ".tailtest", "session.json")
        session: dict = {}
        if os.path.exists(session_path):
            try:
                with open(session_path) as fh:
                    session = json.load(fh)
            except (json.JSONDecodeError, OSError):
                pass

        runners = session.get("runners", {})
        depth = session.get("depth", "standard")
        pending_files = session.get("pending_files", [])
        fix_attempts = session.get("fix_attempts", {})

        context = build_compact_context(
            project_root, runners, depth, pending_files, fix_attempts, agents_md
        )
    else:
        # startup or resume -- full project orientation
        _write_orphaned_report(project_root)
        runners = scan_runners(project_root)
        depth = read_depth(project_root)
        first_session = is_first_session(project_root)
        session = {}
        try:
            session = create_session(project_root, runners, depth)
        except OSError:
            pass

        ramp_up_count = 0
        if source == "startup" and first_session and session:
            try:
                ramp_up_scan(project_root, runners, session)
                ramp_up_count = len(session.get("pending_files", []))
            except Exception:
                ramp_up_count = 0  # Never crash startup

        context = build_startup_context(
            project_root, runners, depth, agents_md,
            ramp_up_count=ramp_up_count,
        )

    if context:
        # Codex SessionStart: emit via hookSpecificOutput.additionalContext
        # (unlike Claude Code which uses plain stdout for SessionStart).
        # If this format does not inject, fall back to plain stdout as well.
        output = json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        })
        print(output)


if __name__ == "__main__":
    main()
