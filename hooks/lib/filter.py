"""Intelligence filter -- language detection and file filtering.

Shared logic between session_start.py, stop.py, and context.py.
All functions are pure (no I/O) except load_ignore_patterns.
"""

from __future__ import annotations

import fnmatch
import os
from typing import Optional

# ---------------------------------------------------------------------------
# Extension -> language mapping
# ---------------------------------------------------------------------------

LANGUAGE_MAP: dict[str, str] = {
    ".py": "python",
    ".pyx": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".vue": "javascript",   # Vue SFCs -- runner detected under javascript key
    ".svelte": "javascript",  # Svelte SFCs
    ".ts": "typescript",
    ".tsx": "typescript",
    ".mts": "typescript",
    ".cts": "typescript",
    ".php": "php",
    ".go": "go",
    ".rb": "ruby",
    ".rs": "rust",
    ".java": "java",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".kts": "kotlin",
}

# ---------------------------------------------------------------------------
# Intelligence filter constants
# ---------------------------------------------------------------------------

SKIP_EXTENSIONS: frozenset[str] = frozenset({
    # Config / data
    ".yaml", ".yml", ".json", ".toml", ".env", ".ini", ".lock",
    ".cfg", ".conf", ".properties", ".plist",
    # Docs
    ".md", ".rst", ".txt", ".adoc", ".asciidoc",
    # Templates / markup
    ".html", ".htm", ".jinja", ".jinja2", ".ejs", ".hbs", ".njk",
    ".twig", ".mustache", ".erb", ".haml",
    # GraphQL schemas
    ".graphql", ".gql",
    # Infrastructure-as-code
    ".tf", ".hcl", ".tfvars",
    # Images / media
    ".svg", ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp",
    ".mp4", ".mp3", ".wav", ".pdf",
    # Styles
    ".css", ".scss", ".sass", ".less", ".styl",
    # Data formats
    ".xml", ".xsd", ".wsdl", ".csv", ".tsv",
    # Protocols / codegen sources
    ".proto", ".thrift", ".avsc",
    # Shell scripts (no standard test runner for hook use)
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    # SQL
    ".sql",
})

# Build-tool config compound suffixes (checked before extension)
BUILD_CONFIG_SUFFIXES: tuple[str, ...] = (
    ".config.js",
    ".config.ts",
    ".config.mjs",
    ".config.cjs",
    ".config.jsx",
    ".config.tsx",
)

# Path fragments that indicate non-testable directories
SKIP_PATH_FRAGMENTS: tuple[str, ...] = (
    "node_modules/",
    ".venv/",
    "venv/",
    ".env/",
    "env/",
    "dist/",
    "build/",
    "generated/",
    ".git/",
    "vendor/",
    "migrations/",
    "db/migrate/",
    "database/migrations/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "target/",
    ".cargo/",
    "coverage/",
    ".nyc_output/",
    ".next/",
    ".nuxt/",
    ".svelte-kit/",
    "k8s/",
    "deploy/",
    "infra/",
)

# Test file name substrings
TEST_NAME_PATTERNS: tuple[str, ...] = (
    "test_",
    "_test.",
    ".test.",
    ".spec.",
    "_spec.",
    "Test.",
    "Tests.",
    "IT.",
)

# Framework boilerplate entry points
FRAMEWORK_BOILERPLATE: frozenset[str] = frozenset({
    "manage.py",
    "wsgi.py",
    "asgi.py",
    "__main__.py",
    "middleware.ts",
    "middleware.js",
})

# Go generated file markers
GO_GENERATED_PREFIXES: tuple[str, ...] = ("mock_",)
GO_GENERATED_SUFFIXES: tuple[str, ...] = ("_mock.go", "_gen.go", ".pb.go")

# JS/TS generated file suffixes
JS_GENERATED_SUFFIXES: tuple[str, ...] = (".generated.ts", ".graphql.ts")

# Languages that must have a configured runner in session.json to proceed.
RUNNER_REQUIRED_LANGUAGES: frozenset[str] = frozenset({"php", "go", "ruby", "rust", "java"})


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def _norm(path: str) -> str:
    """Normalise path separators to forward-slash."""
    return path.replace("\\", "/")


def detect_language(file_path: str) -> Optional[str]:
    """Return the language name for a file path, or None if not recognised."""
    _, ext = os.path.splitext(file_path)
    return LANGUAGE_MAP.get(ext.lower())


def is_test_file(rel_path: str) -> bool:
    """Return True if the filename looks like a test file."""
    name = os.path.basename(rel_path)
    return any(pat in name for pat in TEST_NAME_PATTERNS)


def is_filtered(
    file_path: str,
    project_root: str,
    ignore_patterns: list[str],
) -> bool:
    """Return True when the file should be silently skipped.

    Never reads file content -- content-based checks (re-export barrels,
    type-only TS files, Server Components) are the model's responsibility.
    """
    abs_path = os.path.abspath(file_path)
    rel_path = _norm(os.path.relpath(abs_path, project_root))
    name = os.path.basename(rel_path)
    lower_name = name.lower()

    # 1. .tailtest-ignore patterns (gitignore-style)
    for pat in ignore_patterns:
        if pat.endswith("/"):
            if rel_path.startswith(pat):
                return True
        elif fnmatch.fnmatch(rel_path, pat) or fnmatch.fnmatch(name, pat):
            return True

    # 2. Path fragments (directory-level exclusions)
    for frag in SKIP_PATH_FRAGMENTS:
        if frag in rel_path:
            return True

    # 3. Compound config suffixes before single-ext check
    for suffix in BUILD_CONFIG_SUFFIXES:
        if lower_name.endswith(suffix):
            return True

    # 4. Single-extension exclusions
    _, ext = os.path.splitext(name)
    if ext.lower() in SKIP_EXTENSIONS:
        return True

    # 5. Dockerfile (no extension)
    if lower_name in ("dockerfile",) or lower_name.endswith(".dockerfile"):
        return True

    # 6. Test files
    if is_test_file(rel_path):
        return True

    # 7. Framework boilerplate
    if name in FRAMEWORK_BOILERPLATE:
        return True

    # 8. Go generated files
    if name.endswith(".go"):
        if any(name.startswith(p) for p in GO_GENERATED_PREFIXES):
            return True
        if any(name.endswith(s) for s in GO_GENERATED_SUFFIXES):
            return True

    # 9. JS/TS generated files
    if any(name.endswith(s) for s in JS_GENERATED_SUFFIXES):
        return True

    return False


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
