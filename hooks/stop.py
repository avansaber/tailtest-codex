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
import re
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
from hooks.lib.complexity_scorer import complexity_context_note, score_file
from hooks.lib.history_manager import append_session_to_history
from hooks.lib.last_failures_formatter import compute_last_failures
from hooks.lib.scanner import sweep_mtime_changed
from hooks.lib.scenario_log import append_to_log, build_scenario_entries
from hooks.lib.session import load_session, save_session


_MAX_TRANSCRIPT_TAIL_BYTES = 1024 * 1024
_TOOL_STOP_PATTERNS = (
    re.compile(r"^/tailtest\s+defer\s*[.!]?$", re.IGNORECASE),
    re.compile(
        r"^(?:please\s+)?(?:after\b.{0,200},\s*)?"
        r"invoke\s+no\s+(?:further|more|additional)\s+tools?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:please\s+)?(?:after\b.{0,200},\s*)?"
        r"(?:do not|don't|never)\s+(?:invoke|use|run|call)\s+"
        r"(?:any\s+)?(?:more|further|additional|another)\s+tools?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:please\s+)?(?:after\b.{0,200},\s*)?"
        r"(?:do not|don't|never)\s+(?:invoke|use|run|call)\s+"
        r"(?:any\s+)?tools?\s+after\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"^(?:please\s+)?no\s+(?:more|further|additional)\s+tools?\b",
        re.IGNORECASE,
    ),
)


def _trusted_transcript_path(raw_path: object) -> str | None:
    """Return a Codex-owned transcript path, or None for untrusted locations."""
    if not isinstance(raw_path, str) or not raw_path or "\x00" in raw_path:
        return None

    codex_home = os.environ.get("CODEX_HOME") or os.path.join(
        os.path.expanduser("~"),
        ".codex",
    )
    transcript_path = os.path.normcase(os.path.realpath(raw_path))
    if not transcript_path.endswith(".jsonl") or not os.path.isfile(transcript_path):
        return None

    for directory in ("sessions", "archived_sessions"):
        allowed_root = os.path.normcase(
            os.path.realpath(os.path.join(codex_home, directory))
        )
        try:
            if os.path.commonpath((allowed_root, transcript_path)) == allowed_root:
                return transcript_path
        except ValueError:
            continue
    return None


def _latest_user_message(event: dict) -> str:
    """Read the newest user message from a bounded, Codex-owned transcript tail."""
    transcript_path = _trusted_transcript_path(event.get("transcript_path"))
    if not transcript_path:
        return ""

    try:
        with open(transcript_path, "rb") as transcript:
            transcript.seek(0, os.SEEK_END)
            start = max(0, transcript.tell() - _MAX_TRANSCRIPT_TAIL_BYTES)
            transcript.seek(start)
            if start:
                transcript.readline()
            transcript_tail = transcript.read().decode("utf-8", errors="replace")
    except OSError:
        return ""

    for raw_line in reversed(transcript_tail.splitlines()):
        try:
            record = json.loads(raw_line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(record, dict):
            continue

        payload = record.get("payload")
        if not isinstance(payload, dict):
            continue
        if (
            record.get("type") == "event_msg"
            and payload.get("type") == "user_message"
            and isinstance(payload.get("message"), str)
        ):
            return payload["message"]
        if (
            record.get("type") == "response_item"
            and payload.get("type") == "message"
            and payload.get("role") == "user"
        ):
            content = payload.get("content")
            if not isinstance(content, list):
                return ""
            return "\n".join(
                item["text"]
                for item in content
                if isinstance(item, dict)
                and item.get("type") == "input_text"
                and isinstance(item.get("text"), str)
            )
    return ""


def _user_requested_tool_stop(event: dict) -> bool:
    """Return True only for an explicit directive in the latest user message."""
    in_fence = False
    for line in _latest_user_message(event).splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if any(pattern.search(stripped) for pattern in _TOOL_STOP_PATTERNS):
            return True
    return False


def sweep_changed_files(
    project_root: str,
    turn_start_mtime: float,
    ignore_patterns: list[str],
) -> list[dict]:
    """Walk the project and return files modified after turn_start_mtime.

    Returns a list of dicts: [{path: rel_path, language: lang}, ...]
    Only files that pass is_filtered() and have a known language are returned.

    Thin wrapper kept for back-compat with the v4.7-era test suite. New
    callers should import sweep_mtime_changed from lib.scanner directly.
    """
    return sweep_mtime_changed(project_root, turn_start_mtime, ignore_patterns)


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
        print(json.dumps({}))
        return

    # Load session -- graceful no-op if missing
    session = load_session(project_root)
    if not session.get("runners") and not session.get("session_id"):
        # No active tailtest session
        print(json.dumps({}))
        return

    # Paused session: update mtime timestamp and continue
    if session.get("paused", False):
        session["turn_start_mtime"] = time.time()
        try:
            save_session(project_root, session)
        except OSError:
            pass
        print(json.dumps({}))
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
    session["last_failures"] = compute_last_failures(session)

    # H3: append scenario log entries
    new_entries = build_scenario_entries(session)
    if new_entries:
        session["scenario_log"] = append_to_log(session.get("scenario_log", []), new_entries)
        # A1: persist to cross-session history
        try:
            append_session_to_history(project_root, new_entries)
        except Exception:
            pass

    # H1: store complexity scores for newly qualified files
    configured_depth = session.get("depth", "standard")
    scores = session.get("complexity_scores", {})
    for entry in qualified:
        p = entry.get("path", "")
        if p:
            try:
                sc, _ = score_file(os.path.join(project_root, p))
                scores[p] = sc
            except Exception:
                pass
    session["complexity_scores"] = scores

    if not qualified:
        try:
            save_session(project_root, session)
        except OSError:
            pass
        print(json.dumps({}))
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

    if pending_files and _user_requested_tool_stop(event):
        print(json.dumps({}))
        return

    if not newly_queued:
        # All changed files were already pending -- nothing new to block for
        print(json.dumps({}))
        return

    n = len(newly_queued)
    file_parts = []
    for p in newly_queued[:5]:
        hint = complexity_context_note(os.path.join(project_root, p), configured_depth)
        file_parts.append(f"{p}{' -- ' + hint if hint else ''}")
    if len(newly_queued) > 5:
        file_parts.append(f"+{len(newly_queued) - 5} more")
    paths_str = ", ".join(file_parts)

    reason = (
        f"tailtest: queued {n} file(s) ({paths_str}). "
        f"Read .tailtest/session.json and follow AGENTS.md Step 1."
    )
    print(json.dumps({"decision": "block", "reason": reason}))


if __name__ == "__main__":
    main()
