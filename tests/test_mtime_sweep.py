"""Unit tests for the mtime sweep logic in hooks/stop.py.

Tests: file created after baseline, modified file, pre-existing file skipped,
noisy directories skipped, test files skipped, generated files skipped,
.tailtest-ignore patterns respected, strict > boundary, language detection.
"""

import os
import time

import pytest

from hooks.lib.filter import load_ignore_patterns
from hooks.stop import sweep_changed_files


def _sweep(tmp_path, turn_start_mtime: float, ignore_patterns=None) -> list[dict]:
    return sweep_changed_files(
        str(tmp_path),
        turn_start_mtime,
        ignore_patterns or [],
    )


def _touch(path: str, content: str = "x = 1\n") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(content)


# ---------------------------------------------------------------------------
# Created file detected
# ---------------------------------------------------------------------------


class TestCreatedFileDetected:
    def test_created_file_detected(self, tmp_path):
        baseline = time.time() - 5
        src = tmp_path / "billing.py"
        src.write_text("def billing(): pass\n")
        results = _sweep(tmp_path, baseline)
        paths = [r["path"] for r in results]
        assert "billing.py" in paths

    def test_created_file_has_correct_language(self, tmp_path):
        baseline = time.time() - 5
        src = tmp_path / "billing.py"
        src.write_text("def billing(): pass\n")
        results = _sweep(tmp_path, baseline)
        entry = next(r for r in results if r["path"] == "billing.py")
        assert entry["language"] == "python"


# ---------------------------------------------------------------------------
# Modified file detected
# ---------------------------------------------------------------------------


class TestModifiedFileDetected:
    def test_modified_file_detected(self, tmp_path):
        src = tmp_path / "billing.py"
        src.write_text("def old(): pass\n")
        baseline = time.time()
        time.sleep(0.05)
        src.write_text("def new(): pass\n")
        results = _sweep(tmp_path, baseline)
        paths = [r["path"] for r in results]
        assert "billing.py" in paths


# ---------------------------------------------------------------------------
# Pre-existing file skipped
# ---------------------------------------------------------------------------


class TestPreExistingFileSkipped:
    def test_pre_existing_file_not_detected(self, tmp_path):
        src = tmp_path / "billing.py"
        src.write_text("def billing(): pass\n")
        # Set baseline AFTER the file was written
        baseline = time.time()
        results = _sweep(tmp_path, baseline)
        paths = [r["path"] for r in results]
        assert "billing.py" not in paths


# ---------------------------------------------------------------------------
# Noisy directories skipped
# ---------------------------------------------------------------------------


class TestNoisyDirectoriesSkipped:
    def test_node_modules_skipped(self, tmp_path):
        baseline = time.time() - 5
        nm = tmp_path / "node_modules" / "lodash"
        nm.mkdir(parents=True)
        (nm / "index.js").write_text("module.exports = {}\n")
        results = _sweep(tmp_path, baseline)
        paths = [r["path"] for r in results]
        assert not any("node_modules" in p for p in paths)

    def test_dotgit_skipped(self, tmp_path):
        baseline = time.time() - 5
        git_dir = tmp_path / ".git" / "objects"
        git_dir.mkdir(parents=True)
        (git_dir / "abc123.py").write_text("# git object\n")
        results = _sweep(tmp_path, baseline)
        paths = [r["path"] for r in results]
        assert not any(".git" in p for p in paths)

    def test_venv_skipped(self, tmp_path):
        baseline = time.time() - 5
        venv = tmp_path / ".venv" / "lib" / "python3.12" / "site-packages"
        venv.mkdir(parents=True)
        (venv / "requests.py").write_text("# requests\n")
        results = _sweep(tmp_path, baseline)
        paths = [r["path"] for r in results]
        assert not any(".venv" in p for p in paths)

    def test_dist_skipped(self, tmp_path):
        baseline = time.time() - 5
        dist = tmp_path / "dist"
        dist.mkdir()
        (dist / "bundle.js").write_text("// bundle\n")
        results = _sweep(tmp_path, baseline)
        paths = [r["path"] for r in results]
        assert not any("dist" in p for p in paths)


# ---------------------------------------------------------------------------
# Test file skipped
# ---------------------------------------------------------------------------


class TestTestFileSkipped:
    def test_python_test_file_skipped(self, tmp_path):
        baseline = time.time() - 5
        tests_dir = tmp_path / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_billing.py").write_text("def test_x(): pass\n")
        results = _sweep(tmp_path, baseline)
        paths = [r["path"] for r in results]
        assert not any("test_billing.py" in p for p in paths)

    def test_go_test_file_skipped(self, tmp_path):
        baseline = time.time() - 5
        (tmp_path / "handler_test.go").write_text("package main\n")
        results = _sweep(tmp_path, baseline)
        paths = [r["path"] for r in results]
        assert not any("handler_test.go" in p for p in paths)

    def test_ts_spec_file_skipped(self, tmp_path):
        baseline = time.time() - 5
        (tmp_path / "billing.spec.ts").write_text("describe('x', () => {})\n")
        results = _sweep(tmp_path, baseline)
        paths = [r["path"] for r in results]
        assert not any("billing.spec.ts" in p for p in paths)


# ---------------------------------------------------------------------------
# Generated files skipped
# ---------------------------------------------------------------------------


class TestGeneratedFilesSkipped:
    def test_ts_generated_file_skipped(self, tmp_path):
        baseline = time.time() - 5
        (tmp_path / "types.generated.ts").write_text("export type X = string\n")
        results = _sweep(tmp_path, baseline)
        paths = [r["path"] for r in results]
        assert not any("types.generated.ts" in p for p in paths)

    def test_go_mock_file_skipped(self, tmp_path):
        baseline = time.time() - 5
        (tmp_path / "mock_user.go").write_text("package main\n")
        results = _sweep(tmp_path, baseline)
        paths = [r["path"] for r in results]
        assert not any("mock_user.go" in p for p in paths)


# ---------------------------------------------------------------------------
# Markdown file skipped
# ---------------------------------------------------------------------------


class TestMarkdownSkipped:
    def test_markdown_file_not_queued(self, tmp_path):
        baseline = time.time() - 5
        (tmp_path / "README.md").write_text("# README\n")
        results = _sweep(tmp_path, baseline)
        assert results == []


# ---------------------------------------------------------------------------
# .tailtest-ignore patterns
# ---------------------------------------------------------------------------


class TestTailTestIgnorePatternSkipped:
    def test_ignored_file_not_queued(self, tmp_path):
        ignore_file = tmp_path / ".tailtest-ignore"
        ignore_file.write_text("scripts/seed.py\n")
        baseline = time.time() - 5
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "seed.py").write_text("def seed(): pass\n")
        patterns = load_ignore_patterns(str(tmp_path))
        results = sweep_changed_files(str(tmp_path), baseline, patterns)
        paths = [r["path"] for r in results]
        assert not any("seed.py" in p for p in paths)

    def test_directory_pattern_in_tailtest_ignore(self, tmp_path):
        ignore_file = tmp_path / ".tailtest-ignore"
        ignore_file.write_text("scripts/\n")
        baseline = time.time() - 5
        scripts = tmp_path / "scripts"
        scripts.mkdir()
        (scripts / "deploy.py").write_text("def deploy(): pass\n")
        (scripts / "seed.py").write_text("def seed(): pass\n")
        patterns = load_ignore_patterns(str(tmp_path))
        results = sweep_changed_files(str(tmp_path), baseline, patterns)
        paths = [r["path"] for r in results]
        assert not any("scripts/" in p for p in paths)

    def test_non_ignored_file_still_detected(self, tmp_path):
        ignore_file = tmp_path / ".tailtest-ignore"
        ignore_file.write_text("scripts/\n")
        baseline = time.time() - 5
        (tmp_path / "billing.py").write_text("def billing(): pass\n")
        patterns = load_ignore_patterns(str(tmp_path))
        results = sweep_changed_files(str(tmp_path), baseline, patterns)
        paths = [r["path"] for r in results]
        assert "billing.py" in paths


# ---------------------------------------------------------------------------
# Boundary: strictly greater than
# ---------------------------------------------------------------------------


class TestBoundaryMtimeStrictlyGreater:
    def test_file_at_exactly_turn_start_not_queued(self, tmp_path):
        src = tmp_path / "billing.py"
        src.write_text("def billing(): pass\n")
        exact_mtime = os.path.getmtime(str(src))
        # Baseline is exactly the file's mtime -- strictly greater required
        results = _sweep(tmp_path, exact_mtime)
        paths = [r["path"] for r in results]
        assert "billing.py" not in paths

    def test_file_one_second_after_baseline_is_queued(self, tmp_path):
        baseline = time.time() - 2
        src = tmp_path / "billing.py"
        src.write_text("def billing(): pass\n")
        results = _sweep(tmp_path, baseline)
        paths = [r["path"] for r in results]
        assert "billing.py" in paths


# ---------------------------------------------------------------------------
# Rust file queued
# ---------------------------------------------------------------------------


class TestRustFileQueued:
    def test_rust_source_file_queued(self, tmp_path):
        baseline = time.time() - 5
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        (src_dir / "lib.rs").write_text("pub fn add(a: i32, b: i32) -> i32 { a + b }\n")
        results = _sweep(tmp_path, baseline)
        paths = [r["path"] for r in results]
        assert any("lib.rs" in p for p in paths)
        entry = next(r for r in results if "lib.rs" in r["path"])
        assert entry["language"] == "rust"


# ---------------------------------------------------------------------------
# Language None not queued
# ---------------------------------------------------------------------------


class TestLanguageNoneNotQueued:
    def test_yaml_file_not_queued(self, tmp_path):
        baseline = time.time() - 5
        (tmp_path / "config.yaml").write_text("key: value\n")
        results = _sweep(tmp_path, baseline)
        assert results == []

    def test_json_file_not_queued(self, tmp_path):
        baseline = time.time() - 5
        (tmp_path / "package.json").write_text('{"name":"test"}\n')
        results = _sweep(tmp_path, baseline)
        assert results == []

    def test_csv_file_not_queued(self, tmp_path):
        baseline = time.time() - 5
        (tmp_path / "data.csv").write_text("a,b,c\n")
        results = _sweep(tmp_path, baseline)
        assert results == []


# ---------------------------------------------------------------------------
# Multiple languages in one sweep
# ---------------------------------------------------------------------------


class TestMultipleLanguages:
    def test_python_and_typescript_both_queued(self, tmp_path):
        baseline = time.time() - 5
        (tmp_path / "billing.py").write_text("def billing(): pass\n")
        (tmp_path / "button.ts").write_text("export const x = 1\n")
        results = _sweep(tmp_path, baseline)
        langs = {r["language"] for r in results}
        assert "python" in langs
        assert "typescript" in langs

    def test_empty_directory_returns_empty(self, tmp_path):
        baseline = time.time() - 5
        results = _sweep(tmp_path, baseline)
        assert results == []
