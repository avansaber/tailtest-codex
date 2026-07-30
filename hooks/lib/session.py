"""Session I/O -- load/save .tailtest/session.json and status helpers."""

from __future__ import annotations

import json
import math
import ntpath
import os
import subprocess
import time

from hooks.lib.filter import _norm


MAX_PENDING_FILES = 100
MAX_STATE_ITEMS = 100
MAX_STATE_STRING_CHARS = 512
_ALLOWED_PENDING_STATUSES = {"new-file", "legacy-file", "ramp-up"}
_ALLOWED_DEPTHS = {"simple", "standard", "thorough", "adversarial"}


def _bounded_string(value: object, maximum: int = MAX_STATE_STRING_CHARS) -> str | None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        return None
    return value


def qualify_pending_path(project_root: str, value: object) -> str | None:
    """Return a normalized project-relative path, or None if it escapes."""
    path = _bounded_string(value)
    if path is None or "\x00" in path:
        return None
    path = path.replace("\\", "/")
    drive, _ = os.path.splitdrive(path)
    windows_drive, _ = ntpath.splitdrive(path)
    if drive or windows_drive or os.path.isabs(path):
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
    return None if relative in {"", "."} else relative


def validate_pending_files(project_root: str, raw: object) -> list[dict]:
    """Retain only bounded, well-formed entries contained by project_root."""
    if not isinstance(raw, list):
        return []
    valid = []
    for entry in raw[:MAX_PENDING_FILES]:
        if not isinstance(entry, dict):
            continue
        path = qualify_pending_path(project_root, entry.get("path"))
        language = _bounded_string(entry.get("language"), 64)
        status = _bounded_string(entry.get("status"), 32)
        if (
            path is not None
            and language is not None
            and status in _ALLOWED_PENDING_STATUSES
        ):
            valid.append({"path": path, "language": language, "status": status})
    return valid


def _bounded_string_list(raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [item for item in raw[:MAX_STATE_ITEMS] if _bounded_string(item) is not None]


def _validated_path_list(project_root: str, raw: object) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [
        path
        for value in raw[:MAX_STATE_ITEMS]
        if (path := qualify_pending_path(project_root, value)) is not None
    ]


def _bounded_string_map(raw: object) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    valid = {}
    for key, value in list(raw.items())[:MAX_STATE_ITEMS]:
        safe_key = _bounded_string(key)
        safe_value = _bounded_string(value)
        if safe_key is not None and safe_value is not None:
            valid[safe_key] = safe_value
    return valid


def _validated_path_map(project_root: str, raw: object) -> dict[str, str]:
    """Keep only project-contained source-to-test mappings."""
    if not isinstance(raw, dict):
        return {}
    valid = {}
    for key, value in list(raw.items())[:MAX_STATE_ITEMS]:
        source_path = qualify_pending_path(project_root, key)
        test_path = qualify_pending_path(project_root, value)
        if source_path is not None and test_path is not None:
            valid[source_path] = test_path
    return valid


def _validated_runners(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    valid = {}
    for language, info in list(raw.items())[:32]:
        safe_language = _bounded_string(language, 64)
        if safe_language is None or not isinstance(info, dict):
            continue
        safe_info = dict(info)
        safe_info["command"] = _bounded_string(info.get("command"), 256) or "?"
        safe_info["test_location"] = (
            _bounded_string(info.get("test_location"), 256) or "tests/"
        )
        valid[safe_language] = safe_info
    return valid


def _validated_fix_attempts(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    valid = {}
    for key, value in list(raw.items())[:MAX_STATE_ITEMS]:
        safe_key = _bounded_string(key)
        if (
            safe_key is not None
            and isinstance(value, int)
            and not isinstance(value, bool)
        ):
            valid[safe_key] = min(max(value, 0), 3)
    return valid


def _validated_path_fix_attempts(project_root: str, raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    valid = {}
    for key, value in list(raw.items())[:MAX_STATE_ITEMS]:
        path = qualify_pending_path(project_root, key)
        if path is not None and isinstance(value, int) and not isinstance(value, bool):
            valid[path] = min(max(value, 0), 3)
    return valid


def _finite_number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _validated_numeric_map(raw: object) -> dict[str, int | float]:
    if not isinstance(raw, dict):
        return {}
    valid = {}
    for key, value in list(raw.items())[:MAX_STATE_ITEMS]:
        safe_key = _bounded_string(key)
        if safe_key is not None and _finite_number(value) is not None:
            valid[safe_key] = value
    return valid


def _validated_path_numeric_map(
    project_root: str, raw: object
) -> dict[str, int | float]:
    if not isinstance(raw, dict):
        return {}
    valid = {}
    for key, value in list(raw.items())[:MAX_STATE_ITEMS]:
        path = qualify_pending_path(project_root, key)
        if path is not None and _finite_number(value) is not None:
            valid[path] = value
    return valid


def _validated_dict_list(raw: object) -> list[dict]:
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw[:MAX_STATE_ITEMS] if isinstance(item, dict)]


def _validated_file_records(project_root: str, raw: object) -> list[dict]:
    """Retain bounded records only when their consumed file path is safe."""
    if not isinstance(raw, list):
        return []
    valid = []
    for item in raw[:MAX_STATE_ITEMS]:
        if not isinstance(item, dict):
            continue
        file_path = qualify_pending_path(project_root, item.get("file"))
        if file_path is None:
            continue
        record = {"file": file_path}
        for key in ("reason", "status", "session_id", "timestamp", "classification"):
            value = _bounded_string(item.get(key))
            if value is not None:
                record[key] = value
        attempts = item.get("attempts")
        if isinstance(attempts, int) and not isinstance(attempts, bool):
            record["attempts"] = min(max(attempts, 0), 3)
        valid.append(record)
    return valid


def validate_session_state(project_root: str, raw: object) -> dict:
    """Sanitize project-local state consumed by automatic hooks.

    Unknown keys remain for forward compatibility; every consumed field is
    replaced with a bounded safe value.
    """
    if not isinstance(raw, dict):
        return {}
    session = dict(raw)
    session["session_id"] = _bounded_string(raw.get("session_id"), 128) or ""
    session["pending_files"] = validate_pending_files(
        project_root, raw.get("pending_files", [])
    )
    session["runners"] = _validated_runners(raw.get("runners", {}))
    depth = raw.get("depth")
    session["depth"] = (
        depth if isinstance(depth, str) and depth in _ALLOWED_DEPTHS else "standard"
    )
    session["paused"] = (
        raw.get("paused") if isinstance(raw.get("paused"), bool) else False
    )
    session["touched_files"] = _validated_path_list(
        project_root, raw.get("touched_files", [])
    )
    session["deferred_failures"] = _validated_file_records(
        project_root, raw.get("deferred_failures", [])
    )
    session["generated_tests"] = _validated_path_map(
        project_root, raw.get("generated_tests", {})
    )
    session["fix_attempts"] = _validated_path_fix_attempts(
        project_root, raw.get("fix_attempts", {})
    )
    session["complexity_scores"] = _validated_path_numeric_map(
        project_root, raw.get("complexity_scores", {})
    )
    session["last_failures"] = _validated_file_records(
        project_root, raw.get("last_failures", [])
    )
    session["scenario_log"] = _validated_file_records(
        project_root, raw.get("scenario_log", [])
    )
    turn_start = _finite_number(raw.get("turn_start_mtime", 0.0))
    session["turn_start_mtime"] = turn_start if turn_start is not None else 0.0
    post_tool = _finite_number(
        raw.get("post_tool_last_fire_mtime", session["turn_start_mtime"])
    )
    session["post_tool_last_fire_mtime"] = (
        post_tool if post_tool is not None else session["turn_start_mtime"]
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
