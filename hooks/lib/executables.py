"""Trusted executable resolution for automatic hook subprocesses."""

from __future__ import annotations

import os


def _contained_by(path: str, root: str) -> bool:
    """Return whether canonical *path* is inside canonical *root*."""
    try:
        return os.path.commonpath((path, root)) == root
    except ValueError:
        return False


def _candidate_names(name: str) -> list[str]:
    if os.name != "nt":
        return [name]

    extensions = [
        extension
        for extension in (os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(
            os.pathsep
        )
        if extension
    ]
    if any(name.lower().endswith(extension.lower()) for extension in extensions):
        return [name]
    return [f"{name}{extension}" for extension in extensions]


def resolve_trusted_executable(name: str, project_root: str) -> str | None:
    """Resolve *name* from absolute PATH entries outside the active project.

    Python's Windows executable lookup and :func:`shutil.which` both prefer the
    process current directory. Tailtest hooks intentionally run for untrusted
    projects, so automatic subprocesses must receive an absolute program path
    selected without ambient current-directory search.
    """
    if not name or os.path.dirname(name):
        return None

    canonical_project = os.path.normcase(os.path.realpath(project_root))
    for raw_entry in os.environ.get("PATH", "").split(os.pathsep):
        entry = raw_entry.strip()
        if len(entry) >= 2 and entry[0] == entry[-1] == '"':
            entry = entry[1:-1]
        if not entry or not os.path.isabs(entry):
            continue

        canonical_entry = os.path.normcase(os.path.realpath(entry))
        if _contained_by(canonical_entry, canonical_project):
            continue

        for candidate_name in _candidate_names(name):
            candidate = os.path.join(entry, candidate_name)
            if not os.path.isfile(candidate):
                continue
            if os.name != "nt" and not os.access(candidate, os.X_OK):
                continue

            canonical_candidate = os.path.normcase(os.path.realpath(candidate))
            if _contained_by(canonical_candidate, canonical_project):
                continue
            return canonical_candidate
    return None
