"""Session I/O -- load/save .tailtest/session.json and status helpers."""

from __future__ import annotations

import json
import os
import subprocess
import time

from hooks.lib.filter import _norm


def load_session(project_root: str) -> dict:
    """Load .tailtest/session.json.  Returns minimal empty dict if absent."""
    session_path = os.path.join(project_root, ".tailtest", "session.json")
    if os.path.exists(session_path):
        try:
            with open(session_path) as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "pending_files": [],
        "touched_files": [],
        "runners": {},
        "fix_attempts": {},
        "deferred_failures": [],
        "generated_tests": {},
        "packages": {},
        "last_failures": [],
        "scenario_log": [],
        "complexity_scores": {},
    }


def save_session(project_root: str, session: dict) -> None:
    """Write session dict to .tailtest/session.json."""
    tailtest_dir = os.path.join(project_root, ".tailtest")
    os.makedirs(tailtest_dir, exist_ok=True)
    session_path = os.path.join(tailtest_dir, "session.json")
    with open(session_path, "w") as fh:
        json.dump(session, fh, indent=2)
        fh.write("\n")


def rebase_turn_timestamps(session: dict, now: float | None = None) -> None:
    """Reset per-turn mtime watermarks for a fresh post-compaction baseline."""
    if now is None:
        now = time.time()
    session["turn_start_mtime"] = now
    session["post_tool_last_fire_mtime"] = now


def is_git_tracked(file_path: str, project_root: str) -> bool | None:
    """Return True if tracked by git, False if untracked, None if git unavailable."""
    if not os.path.isdir(os.path.join(project_root, ".git")):
        return None
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", os.path.abspath(file_path)],
            capture_output=True,
            cwd=project_root,
            timeout=2,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def determine_status(
    file_path: str,
    project_root: str,
    touched_files: list[str],
) -> str:
    """Return 'new-file' or 'legacy-file'.

    Git project:  tracked in git -> legacy-file,  untracked -> new-file.
    No-git:       first touch this session -> new-file,  repeat -> legacy-file.
    """
    rel_path = _norm(os.path.relpath(os.path.abspath(file_path), project_root))
    tracked = is_git_tracked(file_path, project_root)
    if tracked is None:
        return "legacy-file" if rel_path in touched_files else "new-file"
    return "legacy-file" if tracked else "new-file"


def find_package_root(
    rel_path: str,
    packages: dict,
) -> str | None:
    """Return the relative path of the deepest package containing rel_path.

    packages: dict keyed by package relative paths (e.g. 'packages/web').
    Returns the key of the best match, or None if no package contains the file.
    """
    rel_path = _norm(rel_path)
    best: str | None = None
    best_len = -1
    for pkg_rel in packages:
        pkg_prefix = _norm(pkg_rel).rstrip("/") + "/"
        if rel_path.startswith(pkg_prefix) and len(pkg_prefix) > best_len:
            best_len = len(pkg_prefix)
            best = pkg_rel
    return best
