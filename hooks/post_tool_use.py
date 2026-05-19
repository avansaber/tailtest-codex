#!/usr/bin/env python3
"""tailtest Codex PostToolUse hook -- per-edit heartbeat.

Fires after every Codex tool call. For file-mutating tools (apply_patch
and patch), identifies the changed file(s) by parsing the tool_input
patch text. For shell-style tools that may write files indirectly, falls
back to an mtime sweep since the last PostToolUse fire. For everything
else, exits silent.

Mid-turn analog of stop.py. Both hooks remain registered: PostToolUse
handles per-edit responsiveness, Stop remains a turn-end safety net that
catches anything PostToolUse missed (e.g. files written by background
processes or via tools whose payload doesn't reveal paths).

Output: writes additionalContext via hookSpecificOutput so newly queued
files surface to the agent in the same turn without blocking the turn.
This matches the Claude Code variant's PostToolUse contract.

Target: under 1 second on a 5,000-file project tree. No LLM calls.
"""

from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hooks.lib.complexity_scorer import complexity_context_note
from hooks.lib.filter import (
    RUNNER_REQUIRED_LANGUAGES,
    detect_language,
    is_filtered,
    load_ignore_patterns,
)
from hooks.lib.scanner import extract_files_from_patch, sweep_mtime_changed
from hooks.lib.session import load_session, save_session

# Codex tools that may modify files. Conservative whitelist; new tool
# names should be added explicitly rather than discovered at runtime.
PATCH_TOOLS = {"apply_patch", "patch"}
SHELL_TOOLS = {"shell", "bash", "exec"}
FILE_MUTATING_TOOLS = PATCH_TOOLS | SHELL_TOOLS


def main() -> None:
    try:
        raw = sys.stdin.read()
        event: dict = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        sys.exit(0)

    tool_name = event.get("tool_name", "") or ""
    tool_input = event.get("tool_input") or {}
    project_root = event.get("cwd", os.getcwd())

    # Quick exit: tool is not in the mutating set
    if tool_name not in FILE_MUTATING_TOOLS:
        sys.exit(0)

    # Quick exit: no active session
    session = load_session(project_root)
    if not session.get("runners") and not session.get("session_id"):
        sys.exit(0)

    # Honor pause state
    if session.get("paused", False):
        sys.exit(0)

    runners: dict = session.get("runners", {})
    ignore_patterns = load_ignore_patterns(project_root)

    # Step 1: extract candidate paths from the tool payload when possible
    candidate_paths: list[str] = []
    if tool_name in PATCH_TOOLS:
        patch_text = (
            tool_input.get("patch")
            or tool_input.get("input")
            or tool_input.get("diff")
            or ""
        )
        if isinstance(patch_text, str):
            candidate_paths = extract_files_from_patch(patch_text)

    # Step 2: if no paths extracted (or shell-style tool), fall back to
    # mtime sweep since the last PostToolUse fire. This catches both
    # shell-driven writes and any patch envelope we couldn't parse.
    if not candidate_paths:
        last_fire = float(
            session.get(
                "post_tool_last_fire_mtime",
                session.get("turn_start_mtime", 0.0),
            )
        )
        swept = sweep_mtime_changed(project_root, last_fire, ignore_patterns)
        candidate_paths = [c["path"] for c in swept]

    # Always advance the post-tool watermark so later fires don't
    # re-discover the same files via mtime sweep.
    session["post_tool_last_fire_mtime"] = time.time()

    # Step 3: qualify each candidate against the filter, language map,
    # and runner-required set.
    qualified: list[dict] = []
    for rel_path in candidate_paths:
        abs_path = (
            rel_path
            if os.path.isabs(rel_path)
            else os.path.join(project_root, rel_path)
        )
        if not os.path.exists(abs_path):
            continue
        if is_filtered(abs_path, project_root, ignore_patterns):
            continue
        language = detect_language(abs_path)
        if not language:
            continue
        if language in RUNNER_REQUIRED_LANGUAGES and language not in runners:
            continue
        norm_rel = (
            rel_path
            if not os.path.isabs(rel_path)
            else os.path.relpath(rel_path, project_root).replace("\\", "/")
        )
        qualified.append({"path": norm_rel, "language": language})

    if not qualified:
        try:
            save_session(project_root, session)
        except OSError:
            pass
        sys.exit(0)

    # Step 4: loop guard. Skip files that ARE test files we generated
    # in this session; otherwise writing a test triggers a queue entry
    # for the test file itself, which would trigger another test write.
    generated_tests: dict = session.get("generated_tests", {})
    generated_test_paths = set(generated_tests.values())
    qualified = [q for q in qualified if q["path"] not in generated_test_paths]

    if not qualified:
        try:
            save_session(project_root, session)
        except OSError:
            pass
        sys.exit(0)

    # Step 5: merge into pending_files. Dedup by path. Track which
    # entries are brand new so we only surface those in the context note.
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
        sys.exit(0)

    # Step 6: emit additionalContext. Non-blocking; Codex shows it as
    # mid-turn context for the agent to act on.
    n = len(newly_queued)
    configured_depth = session.get("depth", "standard")
    file_parts: list[str] = []
    for p in newly_queued[:5]:
        hint = complexity_context_note(
            os.path.join(project_root, p),
            configured_depth,
        )
        file_parts.append(f"{p}{' -- ' + hint if hint else ''}")
    if len(newly_queued) > 5:
        file_parts.append(f"+{len(newly_queued) - 5} more")
    paths_str = ", ".join(file_parts)

    context = (
        f"tailtest: queued {n} file(s) ({paths_str}). "
        f"Write tests now or continue; the Stop hook will re-check at turn end."
    )
    print(json.dumps({"hookSpecificOutput": {"additionalContext": context}}))


if __name__ == "__main__":
    main()
