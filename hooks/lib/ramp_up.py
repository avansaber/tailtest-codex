"""Ramp-up scan -- first-session coverage bootstrap and orphaned report recovery."""

from __future__ import annotations

import fnmatch
import json
import os
import subprocess
from typing import Optional

from hooks.lib.runners import RAMP_UP_EXT_MAP, RAMP_UP_SKIP_DIRS
from hooks.lib.session import save_session

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RAMP_UP_SENTINEL: str = ".ramp-up-initiated"

# Path fragments that indicate non-testable content
_RAMP_UP_SKIP_FRAGMENTS: tuple[str, ...] = (
    "node_modules/", ".venv/", "venv/", ".env/", "env/",
    "dist/", "build/", "generated/", ".git/", "vendor/",
    "migrations/", "db/migrate/", "database/migrations/",
    "__pycache__/", ".pytest_cache/", ".mypy_cache/", ".ruff_cache/",
    "target/", ".cargo/", "coverage/", ".nyc_output/",
    ".next/", ".nuxt/", ".svelte-kit/", ".tailtest/",
)

_RAMP_UP_TEST_PATTERNS: tuple[str, ...] = (
    "test_", "_test.", ".test.", ".spec.", "_spec.", "Test.", "Tests.", "IT.",
)

_RAMP_UP_BOILERPLATE: frozenset[str] = frozenset({
    "manage.py", "wsgi.py", "asgi.py", "__main__.py",
    "middleware.ts", "middleware.js",
})

_RAMP_UP_GO_GENERATED_PREFIXES: tuple[str, ...] = ("mock_",)
_RAMP_UP_GO_GENERATED_SUFFIXES: tuple[str, ...] = ("_mock.go", "_gen.go", ".pb.go")
_RAMP_UP_JS_GENERATED_SUFFIXES: tuple[str, ...] = (".generated.ts", ".graphql.ts")

_RAMP_UP_PATH_SCORE_HIGH: tuple[str, ...] = ("services/", "models/", "app/", "lib/")
_RAMP_UP_PATH_SCORE_MED: tuple[str, ...] = ("src/", "core/", "api/", "controllers/", "handlers/")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_json(path: str) -> Optional[dict]:
    try:
        with open(path) as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def read_ramp_up_limit(project_root: str) -> int:
    """Read ramp_up_limit from .tailtest/config.json.  Default 7."""
    config_path = os.path.join(project_root, ".tailtest", "config.json")
    cfg = _read_json(config_path)
    if cfg is None:
        return 7
    try:
        raw = cfg.get("ramp_up_limit", 7)
        val = int(raw)
        if val == 0:
            return 0
        return max(1, min(15, val))
    except (TypeError, ValueError):
        return 7


def is_first_session(project_root: str) -> bool:
    """True if .tailtest/reports/ has no .md files and no ramp-up sentinel."""
    reports_dir = os.path.join(project_root, ".tailtest", "reports")
    if not os.path.isdir(reports_dir):
        return True
    try:
        for entry in os.scandir(reports_dir):
            if entry.name == RAMP_UP_SENTINEL:
                return False
            if entry.name.endswith(".md"):
                return False
    except OSError:
        return True
    return True


def load_ignore_patterns(project_root: str) -> list[str]:
    """Read .tailtest-ignore from project root.  Returns [] if absent."""
    ignore_path = os.path.join(project_root, ".tailtest-ignore")
    if not os.path.exists(ignore_path):
        return []
    patterns: list[str] = []
    try:
        with open(ignore_path) as fh:
            for line in fh:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    patterns.append(stripped)
    except OSError:
        pass
    return patterns


def _git_commit_counts(project_root: str) -> dict[str, int]:
    """Return {rel_path: commit_count} for all files.  Single git call."""
    if not os.path.isdir(os.path.join(project_root, ".git")):
        return {}
    try:
        result = subprocess.run(
            [
                "git", "-C", project_root, "log",
                "--name-only", "--pretty=format:", "--no-merges", "--max-count=500",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        counts: dict[str, int] = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if line:
                counts[line] = counts.get(line, 0) + 1
        return counts
    except Exception:
        return {}


def _is_ramp_up_filtered(
    rel_path: str,
    fname: str,
    ignore_patterns: list[str],
) -> bool:
    """True when the file should be excluded from ramp-up candidates."""
    lower = fname.lower()

    for pat in ignore_patterns:
        if pat.endswith("/"):
            if rel_path.startswith(pat):
                return True
        elif fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(fname, pat):
            return True

    for frag in _RAMP_UP_SKIP_FRAGMENTS:
        if frag in rel_path:
            return True

    for suffix in (".config.js", ".config.ts", ".config.mjs", ".config.cjs",
                   ".config.jsx", ".config.tsx"):
        if lower.endswith(suffix):
            return True

    if any(pat in fname for pat in _RAMP_UP_TEST_PATTERNS):
        return True

    if fname in _RAMP_UP_BOILERPLATE:
        return True

    if fname.endswith(".go"):
        if any(fname.startswith(p) for p in _RAMP_UP_GO_GENERATED_PREFIXES):
            return True
        if any(fname.endswith(s) for s in _RAMP_UP_GO_GENERATED_SUFFIXES):
            return True

    if any(fname.endswith(s) for s in _RAMP_UP_JS_GENERATED_SUFFIXES):
        return True

    if lower == "dockerfile" or lower.endswith(".dockerfile"):
        return True

    return False


def _has_existing_test(basename: str, abs_source_path: str, project_root: str) -> bool:
    """True if any test file for this source already exists."""
    source_dir = os.path.dirname(abs_source_path)
    siblings = [
        f"{basename}_test.go",
        f"{basename}.test.ts", f"{basename}.spec.ts",
        f"{basename}.test.tsx", f"{basename}.spec.tsx",
        f"{basename}.test.js", f"{basename}.spec.js",
        f"{basename}.test.jsx", f"{basename}.spec.jsx",
    ]
    for sibling in siblings:
        if os.path.exists(os.path.join(source_dir, sibling)):
            return True

    stems = {
        f"test_{basename}", f"{basename}_test",
        f"{basename}.test", f"{basename}.spec",
        f"{basename}_spec",
        f"{basename}Test", f"{basename}Tests",
    }
    for tdir in ("tests/", "__tests__/", "spec/", "test/", "src/test/"):
        abs_tdir = os.path.join(project_root, tdir)
        if not os.path.isdir(abs_tdir):
            continue
        try:
            for _root, _dirs, files in os.walk(abs_tdir):
                for f in files:
                    if os.path.splitext(f)[0] in stems:
                        return True
        except OSError:
            pass
    return False


def _score_candidate(
    rel_path: str,
    basename: str,
    abs_path: str,
    commit_counts: dict[str, int],
    project_root: str,
) -> int:
    """Score a source file for ramp-up selection.  Higher = more important."""
    rel_lower = rel_path.lower()

    git_score = min(commit_counts.get(rel_path, 0), 20) * 2

    if any(frag in rel_lower for frag in _RAMP_UP_PATH_SCORE_HIGH):
        path_score = 30
    elif any(frag in rel_lower for frag in _RAMP_UP_PATH_SCORE_MED):
        path_score = 20
    else:
        path_score = 0

    size_score = 0
    try:
        with open(abs_path, encoding="utf-8", errors="ignore") as fh:
            line_count = sum(1 for _ in fh)
        if line_count < 30:
            size_score = -20
        elif line_count < 80:
            size_score = 0
        elif line_count <= 800:
            size_score = 30
        elif line_count <= 1500:
            size_score = 10
    except OSError:
        pass

    penalty = 100 if _has_existing_test(basename, abs_path, project_root) else 0

    return git_score + path_score + size_score - penalty


# ---------------------------------------------------------------------------
# Ramp-up scan
# ---------------------------------------------------------------------------


def ramp_up_scan(project_root: str, runners: dict, session: dict) -> None:
    """Pre-populate pending_files with the project's most important source files."""
    limit = read_ramp_up_limit(project_root)
    if limit == 0:
        return

    reports_dir = os.path.join(project_root, ".tailtest", "reports")
    try:
        os.makedirs(reports_dir, exist_ok=True)
        open(os.path.join(reports_dir, RAMP_UP_SENTINEL), "w").close()  # noqa: WPS515
    except OSError:
        pass

    ignore_patterns = load_ignore_patterns(project_root)
    commit_counts = _git_commit_counts(project_root)

    candidates: list[tuple[int, str, str]] = []

    for root, dirnames, files in os.walk(project_root):
        dirnames[:] = [
            d for d in dirnames
            if d not in RAMP_UP_SKIP_DIRS and not d.startswith(".")
        ]

        for fname in files:
            abs_path = os.path.join(root, fname)
            if os.path.islink(abs_path):
                continue

            rel_path = os.path.relpath(abs_path, project_root).replace("\\", "/")

            language = RAMP_UP_EXT_MAP.get(os.path.splitext(fname)[1].lower())
            if not language:
                continue

            if _is_ramp_up_filtered(rel_path, fname, ignore_patterns):
                continue

            basename = os.path.splitext(fname)[0]
            score = _score_candidate(rel_path, basename, abs_path, commit_counts, project_root)
            if score > 0:
                candidates.append((score, rel_path, language))

    if not candidates:
        return

    candidates.sort(key=lambda x: x[0], reverse=True)
    top = candidates[:limit]

    session["pending_files"] = [
        {"path": rel_path, "language": lang, "status": "ramp-up"}
        for _, rel_path, lang in top
    ]
    session["ramp_up"] = True

    session_path = os.path.join(project_root, ".tailtest", "session.json")
    try:
        with open(session_path, "w") as fh:
            json.dump(session, fh, indent=2)
            fh.write("\n")
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Orphaned report recovery
# ---------------------------------------------------------------------------


def _write_orphaned_report(project_root: str) -> None:
    """Write report for previous session if SessionEnd never fired."""
    session_path = os.path.join(project_root, ".tailtest", "session.json")
    if not os.path.exists(session_path):
        return
    try:
        with open(session_path) as fh:
            old = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return

    report_path = old.get("report_path")
    if not report_path:
        return
    abs_report = os.path.join(project_root, report_path)
    if os.path.exists(abs_report):
        return
    if not old.get("generated_tests"):
        return

    runners: dict = old.get("runners", {})
    depth: str = old.get("depth", "standard")
    started_at: str = old.get("started_at", "")
    fix_attempts: dict = old.get("fix_attempts", {})
    deferred_failures: list = old.get("deferred_failures", [])
    generated_tests: dict = old.get("generated_tests", {})

    runner_parts = [f"{lang}/{info.get('command', '?')}" for lang, info in runners.items()]
    runner_str = ", ".join(runner_parts) if runner_parts else "no runner"

    lines = [f"# tailtest session -- {started_at}", "",
             f"Runner: {runner_str}  |  Depth: {depth}", "",
             "## Files tested", "",
             "| File | Test file | Result |",
             "|---|---|---|"]

    deferred_paths = {d["file"] for d in deferred_failures if isinstance(d, dict)}
    counts = {"passed": 0, "fixed": 0, "deferred": 0, "unresolved": 0}

    for source_path, test_path in sorted(generated_tests.items()):
        attempts = fix_attempts.get(source_path, 0)
        if source_path in deferred_paths:
            status = "deferred"
            counts["deferred"] += 1
        elif attempts == 0:
            status = "passed"
            counts["passed"] += 1
        elif attempts >= 3:
            status = "unresolved"
            counts["unresolved"] += 1
        else:
            status = f"fixed ({attempts} attempt(s))"
            counts["fixed"] += 1
        lines.append(f"| {source_path} | {test_path} | {status} |")

    total = len(generated_tests)
    parts = [f"{total} file(s) tested"]
    if counts["passed"]:
        parts.append(f"{counts['passed']} passed")
    if counts["fixed"]:
        parts.append(f"{counts['fixed']} fixed")
    if counts["deferred"]:
        parts.append(f"{counts['deferred']} deferred")
    if counts["unresolved"]:
        parts.append(f"{counts['unresolved']} unresolved")
    lines.extend(["", "## Summary", "  |  ".join(parts)])

    content = "\n".join(lines) + "\n"
    try:
        os.makedirs(os.path.dirname(abs_report), exist_ok=True)
        with open(abs_report, "w") as fh:
            fh.write(content)
    except OSError:
        pass
