"""Session I/O -- load/save .tailtest/session.json and status helpers."""

from __future__ import annotations

import json
import math
import os
import subprocess
import time
from typing import Any, Optional

from hooks.lib.executables import resolve_trusted_executable
from hooks.lib.filter import _norm


MAX_PENDING_FILES = 100
MAX_STATE_ITEMS = 100
MAX_STATE_STRING_CHARS = 512
_ALLOWED_PENDING_STATUSES = {"new-file", "legacy-file", "ramp-up"}
_ALLOWED_DEPTHS = {"simple", "standard", "thorough", "adversarial"}


def _bounded_string(
    value: object, *, maximum: int = MAX_STATE_STRING_CHARS
) -> str | None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        return None
    return value


def qualify_pending_path(project_root: str, value: object) -> str | None:
    """Return a normalized project-relative path, or None when it escapes."""
    path = _bounded_string(value)
    if path is None or "\x00" in path:
        return None
    drive, _ = os.path.splitdrive(path)
    if drive or os.path.isabs(path):
        return None

    root_real = os.path.realpath(project_root)
    candidate_real = os.path.realpath(os.path.join(root_real, path))
    try:
        common = os.path.commonpath([root_real, candidate_real])
    except ValueError:
        return None
    if os.path.normcase(common) != os.path.normcase(root_real):
        return None

    relative = _norm(os.path.relpath(candidate_real, root_real))
    if relative in {"", "."}:
        return None
    return relative


def validate_pending_files(project_root: str, raw: object) -> list[dict]:
    """Keep only bounded, well-shaped records contained by project_root."""
    if not isinstance(raw, list):
        return []

    valid: list[dict] = []
    for entry in raw[:MAX_PENDING_FILES]:
        if not isinstance(entry, dict):
            continue
        path = qualify_pending_path(project_root, entry.get("path"))
        language = _bounded_string(entry.get("language"), maximum=64)
        status = _bounded_string(entry.get("status"), maximum=32)
        if path is None or language is None or status not in _ALLOWED_PENDING_STATUSES:
            continue
        valid.append({"path": path, "language": language, "status": status})
    return valid


def _bounded_string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [
        value for value in raw[:MAX_STATE_ITEMS] if _bounded_string(value) is not None
    ]


def _bounded_string_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    valid: dict[str, str] = {}
    for key, value in list(raw.items())[:MAX_STATE_ITEMS]:
        safe_key = _bounded_string(key)
        safe_value = _bounded_string(value)
        if safe_key is not None and safe_value is not None:
            valid[safe_key] = safe_value
    return valid


def _validated_runners(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    valid: dict = {}
    for language, info in list(raw.items())[:32]:
        safe_language = _bounded_string(language, maximum=64)
        if safe_language is None or not isinstance(info, dict):
            continue
        safe_info = dict(info)
        command = _bounded_string(info.get("command"), maximum=256)
        test_location = _bounded_string(info.get("test_location"), maximum=256)
        safe_info["command"] = command or "?"
        safe_info["test_location"] = test_location or "tests/"
        valid[safe_language] = safe_info
    return valid


def _validated_fix_attempts(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    valid: dict[str, int] = {}
    for key, value in list(raw.items())[:MAX_STATE_ITEMS]:
        safe_key = _bounded_string(key)
        if safe_key is None or isinstance(value, bool) or not isinstance(value, int):
            continue
        valid[safe_key] = min(max(value, 0), 3)
    return valid


def _validated_numeric_map(raw: object) -> dict[str, int | float]:
    if not isinstance(raw, dict):
        return {}
    valid: dict[str, int | float] = {}
    for key, value in list(raw.items())[:MAX_STATE_ITEMS]:
        safe_key = _bounded_string(key)
        if safe_key is None or _finite_number(value) is None:
            continue
        valid[safe_key] = value
    return valid


def _validated_dict_list(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    return [dict(value) for value in raw[:MAX_STATE_ITEMS] if isinstance(value, dict)]


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _safe_timestamp(value: object) -> float:
    number = _finite_number(value)
    return number if number is not None else 0.0


def validate_session_state(project_root: str, raw: object) -> dict:
    """Sanitize the project-local fields consumed by automatic hooks."""
    if not isinstance(raw, dict):
        return {}

    session: dict[str, Any] = dict(raw)
    session["pending_files"] = validate_pending_files(
        project_root, raw.get("pending_files", [])
    )
    session["runners"] = _validated_runners(raw.get("runners", {}))
    raw_depth = raw.get("depth")
    session["depth"] = (
        raw_depth
        if isinstance(raw_depth, str) and raw_depth in _ALLOWED_DEPTHS
        else "standard"
    )
    session["paused"] = (
        raw.get("paused") if isinstance(raw.get("paused"), bool) else False
    )
    session["touched_files"] = _bounded_string_list(raw.get("touched_files", []))
    session["deferred_failures"] = _bounded_string_list(
        raw.get("deferred_failures", [])
    )
    session["generated_tests"] = _bounded_string_map(raw.get("generated_tests", {}))
    session["fix_attempts"] = _validated_fix_attempts(raw.get("fix_attempts", {}))
    session["complexity_scores"] = _validated_numeric_map(
        raw.get("complexity_scores", {})
    )
    session["last_failures"] = _validated_dict_list(raw.get("last_failures", []))
    session["scenario_log"] = _validated_dict_list(raw.get("scenario_log", []))
    session["turn_start_mtime"] = _safe_timestamp(raw.get("turn_start_mtime", 0.0))
    session["post_tool_last_fire_mtime"] = _safe_timestamp(
        raw.get("post_tool_last_fire_mtime", session["turn_start_mtime"])
    )
    return session


def load_session(project_root: str) -> dict:
    """Load .tailtest/session.json.  Returns minimal empty dict if absent."""
    session_path = os.path.join(project_root, ".tailtest", "session.json")
    if os.path.exists(session_path):
        try:
            with open(session_path) as fh:
                return validate_session_state(project_root, json.load(fh))
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


def rebase_turn_timestamps(session: dict, now: Optional[float] = None) -> None:
    """Reset per-turn mtime watermarks for a fresh post-compaction baseline."""
    if now is None:
        now = time.time()
    session["turn_start_mtime"] = now
    session["post_tool_last_fire_mtime"] = now


def is_git_tracked(file_path: str, project_root: str) -> Optional[bool]:
    """Return True if tracked by git, False if untracked, None if git unavailable."""
    if not os.path.isdir(os.path.join(project_root, ".git")):
        return None
    git_executable = resolve_trusted_executable("git", project_root)
    if git_executable is None:
        return None
    try:
        result = subprocess.run(
            [
                git_executable,
                "ls-files",
                "--error-unmatch",
                os.path.abspath(file_path),
            ],
            capture_output=True,
            cwd=project_root,
            timeout=2,
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
) -> Optional[str]:
    """Return the relative path of the deepest package containing rel_path.

    packages: dict keyed by package relative paths (e.g. 'packages/web').
    Returns the key of the best match, or None if no package contains the file.
    """
    rel_path = _norm(rel_path)
    best: Optional[str] = None
    best_len = -1
    for pkg_rel in packages:
        pkg_prefix = _norm(pkg_rel).rstrip("/") + "/"
        if rel_path.startswith(pkg_prefix):
            if len(pkg_prefix) > best_len:
                best_len = len(pkg_prefix)
                best = pkg_rel
    return best
