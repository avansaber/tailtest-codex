"""Shared file-sweep helpers for tailtest hooks (Codex variant).

Two strategies for finding the files Codex just touched:

1. `sweep_mtime_changed` -- walk the project tree and pick files whose
   mtime is newer than a watermark. Used by stop.py to catch everything
   the agent did during a turn, and as a fallback by post_tool_use.py
   when the tool payload doesn't surface file paths (e.g. a `shell` tool
   call that wrote files via redirection).

2. `extract_files_from_patch` -- parse an apply_patch tool_input string
   to extract the files being modified. Two patch envelope forms are
   handled: standard unified diff (`diff --git a/path b/path`) and the
   Codex-flavor envelope (`*** Update File: path` / `*** Add File: path`).
   This is the fast, deterministic path for PostToolUse on apply_patch.

No LLM calls. Designed to complete in well under 1 second on a
5,000-file project tree.
"""

from __future__ import annotations

import os
import re
import subprocess

from .filter import detect_language, is_filtered

# Directories pruned during walk for performance.
_SKIP_DIRS = {
    "node_modules", ".venv", "venv", ".env", "env",
    "dist", "build", "generated", ".git", "vendor",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "target", ".cargo", "coverage", ".nyc_output",
    ".next", ".nuxt", ".svelte-kit", ".tailtest",
    "migrations", "k8s", "deploy", "infra",
}

# Standard unified diff header.
_DIFF_PATH_RE = re.compile(r"^diff --git a/(.+?) b/", re.MULTILINE)
# Codex-flavor apply_patch envelope.
_CODEX_PATCH_PATH_RE = re.compile(
    r"^\*\*\*\s+(?:Update|Add|Delete)\s+File:\s*(\S+)\s*$",
    re.MULTILINE,
)


def sweep_mtime_changed(
    project_root: str,
    since_mtime: float,
    ignore_patterns: list[str],
    *,
    require_git_change: bool = False,
) -> list[dict]:
    """Walk project_root and return files modified after since_mtime.

    Returns a list of {path, language} dicts. Only files that pass
    is_filtered() and have a known language are returned. Symlinks are
    skipped. mtime must be strictly greater than since_mtime so files
    at exactly the watermark are treated as pre-existing.

    When require_git_change is true inside a Git worktree, mtime alone is
    insufficient: a tracked file must also appear in `git status`, or it is
    treated as clean churn from checkout/rebase/build/test activity.
    """
    changed: list[dict] = []
    git_changed_paths = (
        _git_changed_paths(project_root) if require_git_change else None
    )

    for root, dirnames, filenames in os.walk(project_root):
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith(".")
        ]

        for filename in filenames:
            abs_path = os.path.join(root, filename)

            if os.path.islink(abs_path):
                continue

            try:
                mtime = os.path.getmtime(abs_path)
            except OSError:
                continue

            if mtime <= since_mtime:
                continue

            rel_path = os.path.relpath(abs_path, project_root).replace("\\", "/")
            if git_changed_paths is not None and rel_path not in git_changed_paths:
                continue

            language = detect_language(abs_path)
            if not language:
                continue

            if is_filtered(abs_path, project_root, ignore_patterns):
                continue

            changed.append({"path": rel_path, "language": language})

    return changed


def _git_changed_paths(project_root: str) -> set[str] | None:
    """Return dirty/untracked project-relative paths, or None outside Git."""
    try:
        inside = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            cwd=project_root,
            text=True,
            timeout=2,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if inside.returncode != 0 or inside.stdout.strip().lower() != "true":
        return None

    try:
        status = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            capture_output=True,
            cwd=project_root,
            timeout=5,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if status.returncode != 0:
        return None

    return _parse_porcelain_paths(status.stdout)


def _parse_porcelain_paths(raw: bytes) -> set[str]:
    """Parse `git status --porcelain=v1 -z` paths into normalized rel paths."""
    paths: set[str] = set()
    entries = raw.decode("utf-8", errors="surrogateescape").split("\0")
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if not entry or len(entry) < 4 or entry[2] != " ":
            continue

        status = entry[:2]
        path = entry[3:]
        if path:
            paths.add(path.replace("\\", "/"))

        if ("R" in status or "C" in status) and index < len(entries):
            old_path = entries[index]
            index += 1
            if old_path:
                paths.add(old_path.replace("\\", "/"))
    return paths


def extract_files_from_patch(patch_text: str) -> list[str]:
    """Extract relative file paths from an apply_patch input string.

    Handles two envelope forms Codex uses for apply_patch:
    - Standard unified diff: `diff --git a/path b/path`
    - Codex-flavor envelope: `*** Update File: path`, `*** Add File: path`,
      `*** Delete File: path`

    Returns paths in first-seen order with duplicates removed.
    """
    if not isinstance(patch_text, str) or not patch_text:
        return []

    paths: list[str] = []
    paths.extend(_DIFF_PATH_RE.findall(patch_text))
    paths.extend(_CODEX_PATCH_PATH_RE.findall(patch_text))

    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        normalized = p.replace("\\", "/")
        if normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out
